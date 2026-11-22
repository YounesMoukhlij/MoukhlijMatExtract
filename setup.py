# setup.py
"""The settings of the package are in pyproject.toml. This only adds one step to the build: the repository's
resources/configs/ (every job file) and docs/ (the user's documents) are copied into the package, as mme_home/configs and
mme_home/docs, so that an installed copy can make them in ~/MoukhlijMatExtract (see mme_home/__init__.py)."""

import shutil
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py

HERE = Path(__file__).resolve().parent
# Each kind: (where it is in the repository, which files).
SHIPPED = {"configs": ("resources/configs", "*.yaml"), "docs": ("docs", "*.md")}
MAINTAINER_ONLY = {"PUBLISHING.md"}


class BuildWithHomeFiles(build_py):
    def run(self):
        super().run()
        for kind, (source_dir, pattern) in SHIPPED.items():
            target = Path(self.build_lib) / "mme_home" / kind
            target.mkdir(parents=True, exist_ok=True)
            for source in sorted((HERE / source_dir).glob(pattern)):
                if source.name not in MAINTAINER_ONLY:
                    shutil.copyfile(source, target / source.name)


setup(cmdclass={"build_py": BuildWithHomeFiles})
