"""Usage: python -m evals run <api_base_url>"""

import sys

from evals.run import main

if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "run":
        sys.exit("Usage: python -m evals run <api_base_url>")
    sys.argv = [sys.argv[0], sys.argv[2]]
    main()
