"""DAB task entrypoint: copy S3 objects into the staging volume."""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), ".."))

from file_copy.s3_copy import run  # noqa: E402

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config-dir", required=True)
    args = parser.parse_args()
    run(args.config_dir)
