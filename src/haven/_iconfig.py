"""
Provide beamline configuration from the iconfig.toml file.

Example TOML configuration file: iconfig_default.toml

"""

__all__ = [
    "load_config",
]

import argparse
import logging
import os
import pathlib
from contextlib import contextmanager
from copy import deepcopy
from pprint import pprint
from typing import Sequence

import tomli
from mergedeep import merge

log = logging.getLogger(__name__)


CONFIG_FILES = [
    pathlib.Path(__file__).parent / "iconfig_default.toml",
    pathlib.Path("~/bluesky/").expanduser() / "iconfig.toml",
    pathlib.Path("~/bluesky/instrument").expanduser() / "iconfig.toml",
]


_local_overrides = {}


def load_files(file_paths: Sequence[pathlib.Path]):
    """Generate the configs for files as dictionaries."""
    for fp in file_paths:
        if fp.exists():
            with open(fp, mode="rb") as fp:
                log.debug(f"Loading config file: {fp}")
                config = tomli.load(fp)
                yield config

        else:
            log.debug(f"Could not find config file, skipping: {fp}")


def load_config(file_paths: Sequence[pathlib.Path] = CONFIG_FILES):
    """Load TOML config files.

    Will load files specified in *file_paths* and $HAVEN_CONFIG_FILES
    environmental variable.

    """
    file_paths = list(file_paths).copy()
    # Add config file from environmental variable
    try:
        file_paths.extend(
            [
                pathlib.Path(fp.strip())
                for fp in os.environ["HAVEN_CONFIG_FILES"].split(",")
            ]
        )
    except KeyError:
        pass
    # Load configuration from TOML files
    config = {}
    merge(config, *load_files(file_paths), _local_overrides)
    return config


def print_config_value(args: Sequence[str] = None):
    """Print a config value from TOML files.

    Parameters
    ----------
    key
      The path to the value to retrieve from config files. Sections
      should be separated by dots, e.g. "shutter.A.open_pv"

    """
    # Set up command line arguments
    parser = argparse.ArgumentParser(
        prog="haven_config",
        description="Retrieve a value from Haven's config files.",
    )
    parser.add_argument("key", help="The dot-separated key to look up.")
    args = parser.parse_args(args=args)
    # Get the keys from the config file
    value = load_config()
    for part in args.key.split("."):
        value = value[part]
    try:
        value = value.strip()
    except AttributeError:
        # It's not a simple string, so pretty print it
        pprint(value)
    else:
        # Simple string, so just print it
        print(value)


@contextmanager
def beamline_connected(is_connected=True):
    global _local_overrides
    # Save old value
    old_dict = deepcopy(_local_overrides)
    # Set temporary value
    if "beamline" not in _local_overrides.keys():
        _local_overrides["beamline"] = {}
    _local_overrides["beamline"]["is_connected"] = is_connected
    # Return to enclosing code
    yield
    # Restore old value
    _local_overrides = old_dict


# -----------------------------------------------------------------------------
# :author:    Mark Wolfman
# :email:     wolfman@anl.gov
# :copyright: Copyright © 2023, UChicago Argonne, LLC
#
# Distributed under the terms of the 3-Clause BSD License
#
# The full license is in the file LICENSE, distributed with this software.
#
# DISCLAIMER
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
# A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
# HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
# LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
# DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
# THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
#
# -----------------------------------------------------------------------------
