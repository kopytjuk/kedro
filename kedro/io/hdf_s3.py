# Copyright 2018-2019 QuantumBlack Visual Analytics Limited
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES
# OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, AND
# NONINFRINGEMENT. IN NO EVENT WILL THE LICENSOR OR OTHER CONTRIBUTORS
# BE LIABLE FOR ANY CLAIM, DAMAGES, OR OTHER LIABILITY, WHETHER IN AN
# ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF, OR IN
# CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
#
# The QuantumBlack Visual Analytics Limited (“QuantumBlack”) name and logo
# (either separately or in combination, “QuantumBlack Trademarks”) are
# trademarks of QuantumBlack. The License does not grant you any right or
# license to the QuantumBlack Trademarks. You may not use the QuantumBlack
# Trademarks or any confusingly similar mark as a trademark for your product,
#     or use the QuantumBlack Trademarks in any other manner that might cause
# confusion in the marketplace, including but not limited to in advertising,
# on websites, or on software.
#
# See the License for the specific language governing permissions and
# limitations under the License.

"""``HDFS3DataSet`` loads and saves data to an hdf file in S3. The
underlying functionality is supported by pandas HDFStore and PyTables,
so it supports all allowed PyTables options for loading and saving hdf files.
"""
from typing import Any, Dict, Optional

import pandas as pd
from s3fs import S3FileSystem

from kedro.io.core import (
    AbstractDataSet,
    DataSetError,
    ExistsMixin,
    S3PathVersionMixIn,
    Version,
)

HDFSTORE_DRIVER = "H5FD_CORE"


# pylint: disable=too-many-instance-attributes
class HDFS3DataSet(AbstractDataSet, ExistsMixin, S3PathVersionMixIn):
    """``HDFS3DataSet`` loads and saves data to a S3 bucket. The
    underlying functionality is supported by pandas, so it supports all
    allowed pandas options for loading and saving hdf files.

    Example:
    ::
        >>> from kedro.io import HDFS3DataSet
        >>> import pandas as pd
        >>>
        >>> data = pd.DataFrame({'col1': [1, 2], 'col2': [4, 5],
        >>>                      'col3': [5, 6]})
        >>>
        >>> data_set = HDFS3DataSet(filepath="test.hdf",
        >>>                         bucket_name="test_bucket",
        >>>                         key="test_hdf_key",
        >>>                         load_args=None,
        >>>                         save_args=None)
        >>> data_set.save(data)
        >>> reloaded = data_set.load()
        >>>
        >>> assert data.equals(reloaded)

    """

    # pylint: disable=too-many-arguments
    def __init__(
        self,
        filepath: str,
        bucket_name: str,
        key: str,
        credentials: Optional[Dict[str, Any]] = None,
        load_args: Dict[str, Any] = None,
        save_args: Dict[str, Any] = None,
        version: Version = None,
    ) -> None:
        """Creates a new instance of ``HDFS3DataSet`` pointing to a concrete
        hdf file on S3.

        Args:
            filepath: Path to an hdf file.
            bucket_name: S3 bucket name.
            key: Identifier to the group in the HDF store.
            credentials: Credentials to access the S3 bucket, such as
                ``aws_access_key_id``, ``aws_secret_access_key``.
            load_args: PyTables options for loading hdf files.
                Here you can find all available arguments:
                https://www.pytables.org/usersguide/libref/top_level.html#tables.open_file
                All defaults are preserved.
            save_args: PyTables options for saving hdf files.
                Here you can find all available arguments:
                https://www.pytables.org/usersguide/libref/top_level.html#tables.open_file
                All defaults are preserved.
            version: If specified, should be an instance of
                ``kedro.io.core.Version``. If its ``load`` attribute is
                None, the latest version will be loaded. If its ``save``
                attribute is None, save version will be autogenerated.

        """
        default_load_args = {}
        default_save_args = {}
        self._filepath = filepath
        self._key = key
        self._bucket_name = bucket_name
        self._credentials = credentials if credentials else {}
        self._load_args = (
            {**default_load_args, **load_args}
            if load_args is not None
            else default_load_args
        )
        self._save_args = (
            {**default_load_args, **save_args}
            if save_args is not None
            else default_save_args
        )
        self._version = version
        self._s3 = S3FileSystem(client_kwargs=self._credentials)

    @property
    def _client(self):
        return self._s3.s3

    def _load(self) -> pd.DataFrame:
        load_key = self._get_load_path(
            self._client, self._bucket_name, self._filepath, self._version
        )

        with self._s3.open(
            "{}/{}".format(self._bucket_name, load_key), mode="rb"
        ) as s3_file:
            binary_data = s3_file.read()

        with pd.HDFStore(
            self._filepath,
            mode="r",
            driver=HDFSTORE_DRIVER,
            driver_core_backing_store=0,
            driver_core_image=binary_data,
            **self._load_args,
        ) as store:
            return store[self._key]

    def _save(self, data: pd.DataFrame) -> None:
        save_key = self._get_save_path(
            self._client, self._bucket_name, self._filepath, self._version
        )

        with pd.HDFStore(
            self._filepath,
            mode="w",
            driver=HDFSTORE_DRIVER,
            driver_core_backing_store=0,
            **self._save_args,
        ) as store:
            store[self._key] = data
            # pylint: disable=protected-access
            binary_data = store._handle.get_file_image()

        with self._s3.open(
            "{}/{}".format(self._bucket_name, save_key), mode="wb"
        ) as s3_file:
            # Only binary read and write modes are implemented for S3Files
            s3_file.write(binary_data)

        load_key = self._get_load_path(
            self._client, self._bucket_name, self._filepath, self._version
        )
        self._check_paths_consistency(load_key, save_key)

    def _exists(self) -> bool:
        try:
            load_key = self._get_load_path(
                self._client, self._bucket_name, self._filepath, self._version
            )
        except DataSetError:
            return False

        args = (self._client, self._bucket_name, load_key)
        if any(key == load_key for key in self._list_objects(*args)):
            with self._s3.open(
                "{}/{}".format(self._bucket_name, load_key), mode="rb"
            ) as s3_file:
                binary_data = s3_file.read()

            with pd.HDFStore(
                self._filepath,
                mode="r",
                driver=HDFSTORE_DRIVER,
                driver_core_backing_store=0,
                driver_core_image=binary_data,
                **self._load_args,
            ) as store:
                key_with_slash = (
                    self._key if self._key.startswith("/") else "/" + self._key
                )
                return key_with_slash in store.keys()
        return False

    def _describe(self) -> Dict[str, Any]:
        return dict(
            filepath=self._filepath,
            bucket_name=self._bucket_name,
            key=self._key,
            load_args=self._load_args,
            save_args=self._save_args,
            version=self._version,
        )
