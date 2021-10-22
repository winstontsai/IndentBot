import argparse
import time
import sys

import indent

def get_args():
    parser = argparse.ArgumentParser(description = 'Bot that helps maintain consistent and correct indentation in discussion pages on Wikipedia.')
    parser.add_argument('-v', '--verbose', action='store_true',
        help='print links to the diffs using {{Diff2}}.')
    parser.add_argument('-l', '--limit', type=int, default=None,
        help='maximum number of edits to make.')   

    return parser.parse_args()


if __name__ == '__main__':
    args = get_args()
    indent.main(limit=args.limit, quiet=not args.verbose)