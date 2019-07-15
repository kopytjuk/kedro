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
# The QuantumBlack Visual Analytics Limited ("QuantumBlack") name and logo
# (either separately or in combination, "QuantumBlack Trademarks") are
# trademarks of QuantumBlack. The License does not grant you any right or
# license to the QuantumBlack Trademarks. You may not use the QuantumBlack
# Trademarks or any confusingly similar mark as a trademark for your product,
#     or use the QuantumBlack Trademarks in any other manner that might cause
# confusion in the marketplace, including but not limited to in advertising,
# on websites, or on software.
#
# See the License for the specific language governing permissions and
# limitations under the License.
import json
from os.path import join
from pathlib import Path

import click
from mock import patch
from pytest import fixture, mark, raises, warns

from kedro import __version__ as version
from kedro.cli.cli import _get_plugin_command_groups, _init_plugins, cli
from kedro.cli.utils import (
    CommandCollection,
    KedroCliError,
    export_nodes,
    forward_command,
    get_pkg_version,
)

PACKAGE_NAME = "my_project"


@click.group(name="stub_cli")
def stub_cli():
    """Stub CLI group description."""
    print("group callback")


@stub_cli.command(name="stub_command")
def stub_command():
    print("command callback")


@forward_command(stub_cli, name="forwarded_command")
def forwarded_command(args):
    print("fred", args)


@forward_command(stub_cli, name="forwarded_help", forward_help=True)
def forwarded_help(args):
    print("fred", args)


@forward_command(stub_cli)
def unnamed(args):
    print("fred", args)


@fixture
def invoke_result(cli_runner, request):
    cmd_collection = CommandCollection(("Commands", [cli, stub_cli]))
    return cli_runner.invoke(cmd_collection, request.param)


@fixture
def project_path(tmp_path):
    temp = Path(str(tmp_path))
    return Path(temp / "some/path/to/my_project")


@fixture
def nodes_path(project_path):
    path = project_path / "src" / PACKAGE_NAME / "nodes"
    path.mkdir(parents=True)
    return path


@fixture
def requirements_file(tmp_path):
    body = "\n".join(["SQLAlchemy>=1.2.0, <2.0", "pandas==0.23.0", "toposort"]) + "\n"
    reqs_file = tmp_path / "requirements.txt"
    reqs_file.write_text(body)
    yield reqs_file


class TestCliCommands:
    def test_cli(self, cli_runner):
        """Run `kedro` without arguments."""
        result = cli_runner.invoke(cli, [])

        assert result.exit_code == 0
        assert "kedro" in result.output

    def test_print_version(self, cli_runner):
        """Check that `kedro --version` and `kedro -V` outputs contain
        the current package version."""
        result = cli_runner.invoke(cli, ["--version"])

        assert result.exit_code == 0
        assert version in result.output

        result_abr = cli_runner.invoke(cli, ["-V"])
        assert result_abr.exit_code == 0
        assert version in result_abr.output

    def test_info_contains_qb(self, cli_runner):
        """Check that `kedro info` output contains
        reference to QuantumBlack."""
        result = cli_runner.invoke(cli, ["info"])

        assert result.exit_code == 0
        assert "QuantumBlack" in result.output

    def test_help(self, cli_runner):
        """Check that `kedro --help` returns a valid help message."""
        result = cli_runner.invoke(cli, ["--help"])

        assert result.exit_code == 0
        assert "kedro" in result.output

        result = cli_runner.invoke(cli, ["-h"])
        assert result.exit_code == 0
        assert "-h, --help     Show this message and exit." in result.output

    @patch("webbrowser.open")
    def test_docs(self, patched_browser, cli_runner):
        """Check that `kedro docs` opens a correct file in the browser."""
        result = cli_runner.invoke(cli, ["docs"])

        assert result.exit_code == 0
        for each in ("Opening file", join("html", "index.html")):
            assert each in result.output

        patched_browser.assert_called_once()
        args, _ = patched_browser.call_args
        for each in ("file://", join("kedro", "html", "index.html")):
            assert each in args[0]


class TestCommandCollection:
    @mark.parametrize("invoke_result", [["stub_command"]], indirect=True)
    def test_found(self, invoke_result):
        """Test calling existing command."""
        assert invoke_result.exit_code == 0
        assert "group callback" not in invoke_result.output
        assert "command callback" in invoke_result.output

    def test_found_reverse(self, cli_runner):
        """Test calling existing command."""
        cmd_collection = CommandCollection(("Commands", [stub_cli, cli]))
        invoke_result = cli_runner.invoke(cmd_collection, ["stub_command"])
        assert invoke_result.exit_code == 0
        assert "group callback" in invoke_result.output
        assert "command callback" in invoke_result.output

    @mark.parametrize("invoke_result", [["not_found"]], indirect=True)
    def test_not_found(self, invoke_result):
        """Test calling nonexistent command."""
        assert invoke_result.exit_code == 2
        assert "No such command" in invoke_result.output

    @mark.parametrize("invoke_result", [[]], indirect=True)
    def test_help(self, invoke_result):
        """Check that help output includes stub_cli group description."""
        assert invoke_result.exit_code == 0
        assert "Stub CLI group description" in invoke_result.output
        assert "Kedro is a CLI" in invoke_result.output


class TestForwardCommand:
    def test_regular(self, cli_runner):
        """Test forwarded command invocation."""
        result = cli_runner.invoke(stub_cli, ["forwarded_command", "bob"])
        assert result.exit_code == 0, result.output
        assert "bob" in result.output
        assert "fred" in result.output
        assert "--help" not in result.output
        assert "forwarded_command" not in result.output

    def test_unnamed(self, cli_runner):
        """Test forwarded command invocation."""
        result = cli_runner.invoke(stub_cli, ["unnamed", "bob"])
        assert result.exit_code == 0, result.output
        assert "bob" in result.output
        assert "fred" in result.output
        assert "--help" not in result.output
        assert "forwarded_command" not in result.output

    def test_help(self, cli_runner):
        """Test help output for the command with help flags not forwarded."""
        result = cli_runner.invoke(stub_cli, ["forwarded_command", "bob", "--help"])
        assert result.exit_code == 0, result.output
        assert "bob" not in result.output
        assert "fred" not in result.output
        assert "--help" in result.output
        assert "forwarded_command" in result.output

    def test_forwarded_help(self, cli_runner):
        """Test help output for the command with forwarded help flags."""
        result = cli_runner.invoke(stub_cli, ["forwarded_help", "bob", "--help"])
        assert result.exit_code == 0, result.output
        assert "bob" in result.output
        assert "fred" in result.output
        assert "--help" in result.output
        assert "forwarded_help" not in result.output


class TestCliUtils:
    def test_get_pkg_version(self, requirements_file):
        """Test get_pkg_version(), which extracts package version
        from the provided requirements file."""
        sa_version = "SQLAlchemy>=1.2.0, <2.0"
        assert get_pkg_version(requirements_file, "SQLAlchemy") == sa_version
        assert get_pkg_version(requirements_file, "pandas") == "pandas==0.23.0"
        assert get_pkg_version(requirements_file, "toposort") == "toposort"
        with raises(KedroCliError):
            get_pkg_version(requirements_file, "nonexistent")
        with raises(KedroCliError):
            non_existent_file = str(requirements_file) + "-nonexistent"
            get_pkg_version(non_existent_file, "pandas")

    def test_export_nodes(self, project_path, nodes_path):
        nodes = json.dumps(
            {
                "cells": [
                    {
                        "cell_type": "code",
                        "source": "print('hello world')",
                        "metadata": {"tags": ["node"]},
                    },
                    {
                        "cell_type": "code",
                        "source": "print(10+5)",
                        "metadata": {"tags": ["node"]},
                    },
                    {"cell_type": "code", "source": "a = 10", "metadata": {}},
                ]
            }
        )
        notebook_file = project_path / "notebook.ipynb"
        notebook_file.write_text(nodes)

        output_path = nodes_path / "{}.py".format(notebook_file.stem)
        export_nodes(notebook_file, output_path)

        assert output_path.is_file()
        assert output_path.read_text() == "print('hello world')\nprint(10+5)\n"

    def test_export_nodes_different_notebook_paths(self, project_path, nodes_path):
        nodes = json.dumps(
            {
                "cells": [
                    {
                        "cell_type": "code",
                        "source": "print('hello world')",
                        "metadata": {"tags": ["node"]},
                    }
                ]
            }
        )
        notebook_file1 = project_path / "notebook1.ipynb"
        notebook_file1.write_text(nodes)
        output_path1 = nodes_path / "notebook1.py"

        notebook_file2 = nodes_path / "notebook2.ipynb"
        notebook_file2.write_text(nodes)
        output_path2 = nodes_path / "notebook2.py"

        export_nodes(notebook_file1, output_path1)
        export_nodes(notebook_file2, output_path2)

        assert output_path1.read_text() == "print('hello world')\n"
        assert output_path2.read_text() == "print('hello world')\n"

    def test_export_nodes_nothing_to_write(self, project_path, nodes_path):
        nodes = json.dumps(
            {
                "cells": [
                    {
                        "cell_type": "code",
                        "source": "print('hello world')",
                        "metadata": {},
                    },
                    {
                        "cell_type": "text",
                        "source": "hello world",
                        "metadata": {"tags": ["node"]},
                    },
                ]
            }
        )
        notebook_file = project_path / "notebook.iypnb"
        notebook_file.write_text(nodes)

        with warns(UserWarning, match="Skipping notebook"):
            output_path = nodes_path / "{}.py".format(notebook_file.stem)
            export_nodes(notebook_file, output_path)

        output_path = nodes_path / "notebook.py"
        assert not output_path.exists()

    def test_export_nodes_overwrite(self, project_path, nodes_path):
        existing_nodes = nodes_path / "notebook.py"
        existing_nodes.touch()
        existing_nodes.write_text("original")

        nodes = json.dumps(
            {
                "cells": [
                    {
                        "cell_type": "code",
                        "source": "print('hello world')",
                        "metadata": {"tags": ["node"]},
                    }
                ]
            }
        )
        notebook_file = project_path / "notebook.iypnb"
        notebook_file.write_text(nodes)

        output_path = nodes_path / "{}.py".format(notebook_file.stem)
        export_nodes(notebook_file, output_path)

        assert output_path.is_file()
        assert output_path.read_text() == "print('hello world')\n"

    def test_export_nodes_json_error(self, nodes_path):
        random_file = nodes_path / "notebook.txt"
        random_file.touch()
        random_file.write_text("original")
        output_path = nodes_path / "{}.py".format(random_file.stem)

        pattern = "Provided filepath is not a Jupyter notebook"
        with raises(KedroCliError, match=pattern):
            export_nodes(random_file, output_path)


@fixture
def entry_points(mocker):
    return mocker.patch("pkg_resources.iter_entry_points")


@fixture
def entry_point(mocker, entry_points):
    ep = mocker.MagicMock()
    entry_points.return_value = [ep]
    return ep


class TestEntryPoints:
    def test_project_groups(self, entry_points, entry_point):
        entry_point.load.return_value = "groups"
        groups = _get_plugin_command_groups("project")
        assert groups == ["groups"]
        entry_points.assert_called_once_with(group="kedro.project_commands")

    def test_project_error_is_caught(self, entry_points, entry_point):
        entry_point.load.side_effect = Exception()
        groups = _get_plugin_command_groups("project")
        assert groups == []
        entry_points.assert_called_once_with(group="kedro.project_commands")

    def test_global_groups(self, entry_points, entry_point):
        entry_point.load.return_value = "groups"
        groups = _get_plugin_command_groups("global")
        assert groups == ["groups"]
        entry_points.assert_called_once_with(group="kedro.global_commands")

    def test_global_error_is_caught(self, entry_points, entry_point):
        entry_point.load.side_effect = Exception()
        groups = _get_plugin_command_groups("global")
        assert groups == []
        entry_points.assert_called_once_with(group="kedro.global_commands")

    def test_init(self, entry_points, entry_point):
        _init_plugins()
        entry_points.assert_called_once_with(group="kedro.init")
        entry_point.load().assert_called_once_with()

    def test_init_error_is_caught(self, entry_points, entry_point):
        entry_point.load.side_effect = Exception()
        _init_plugins()
        entry_points.assert_called_once_with(group="kedro.init")
