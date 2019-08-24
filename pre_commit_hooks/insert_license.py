from __future__ import print_function
import argparse, sys
from fuzzywuzzy import fuzz

FUZZY_MATCH_TODO_COMMENT = " TODO: This license is not consistent with license used in the project"
SKIP_LICENSE_INSERTION_COMMENT = "SKIP LICENSE INSERTION"
EXTRA_FUZZY_LICENSE_LINES = 3


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('filenames', nargs='*', help='filenames to check')
    parser.add_argument('--license-filepath', default='LICENSE.txt')
    parser.add_argument('--comment-style', default='#',
                        help='Can be a single prefix or a triplet: '
                             '<comment-sart>|<comment-prefix>|<comment-end>'
                             'E.g.: /*| *| */')
    parser.add_argument('--detect-license-in-X-top-lines', type=int, default=5)
    parser.add_argument('--fuzzy-match-generates-todo', action='store_true')
    parser.add_argument('--fuzzy-ratio-cut-off', type=int, default=85)
    parser.add_argument('--fuzzy-match-todo-comment', default=FUZZY_MATCH_TODO_COMMENT)
    parser.add_argument('--skip-license-insertion-comment', default=SKIP_LICENSE_INSERTION_COMMENT)
    parser.add_argument('--remove-header', action='store_true')
    args = parser.parse_args(argv)

    if '|' in args.comment_style:
        comment_start, comment_prefix, comment_end = args.comment_style.split('|')
    else:
        comment_start, comment_prefix, comment_end = None, args.comment_style, None

    with open(args.license_filepath) as license_file:
        plain_license = license_file.readlines()

    prefixed_license = ['{}{}{}'.format(comment_prefix, ' ' if line.strip() else '', line)
                        for line in plain_license]

    eol = '\r\n' if prefixed_license[0][-2:] == '\r\n' else '\n'
    num_extra_lines = 0
    if not prefixed_license[-1].endswith(eol):
        prefixed_license[-1] += eol
        num_extra_lines += 1
    if comment_start:
        prefixed_license = [comment_start + eol] + prefixed_license
        num_extra_lines += 1
    if comment_end:
        prefixed_license = prefixed_license + [comment_end + eol]
        num_extra_lines += 1

    changed_files = []

    process_files(args, changed_files, comment_prefix, eol, num_extra_lines, plain_license, prefixed_license)

    if changed_files:
        print('')
        print('Some sources were modified by the hook {}. Now aborting the commit.'.format(changed_files))
        print('You can check the changes made. Then simply "git add --update ." and re-commit')
        return 1
    return 0

# pylint: disable=too-many-arguments
def process_files(args, changed_files, comment_prefix, eol, num_extra_lines, plain_license, prefixed_license):
    for src_filepath in args.filenames:
        with open(src_filepath) as src_file:
            src_file_content = src_file.readlines()
        if skip_license_insert_or_todo_found(
                src_file_content=src_file_content,
                skip_license_insertion_comment=args.skip_license_insertion_comment,
                fuzzy_match=args.fuzzy_match_generates_todo,
                fuzzy_match_todo_comment=args.fuzzy_match_todo_comment,
                top_lines_count=args.detect_license_in_X_top_lines):
            continue
        license_header_index = find_license_header_index(
            src_file_content=src_file_content,
            prefixed_license=prefixed_license,
            top_lines_count=args.detect_license_in_X_top_lines)
        fuzzy_match_header_index = None
        if args.fuzzy_match_generates_todo and license_header_index is None:
            fuzzy_match_header_index = fuzzy_find_license_header_index(
                src_file_content=src_file_content,
                plain_license=plain_license,
                comment_prefix=comment_prefix,
                top_lines_count=args.detect_license_in_X_top_lines,
                fuzzy_ratio_cut_off=args.fuzzy_ratio_cut_off,
                num_extra_lines=num_extra_lines
            )
        if license_header_index is not None:
            if license_found(remove_header=args.remove_header,
                             license_header_index=license_header_index,
                             prefixed_license=prefixed_license,
                             src_file_content=src_file_content,
                             src_filepath=src_filepath):
                changed_files.append(src_filepath)
        else:
            if fuzzy_match_header_index is not None:
                if fuzzy_license_found(comment_prefix=comment_prefix,
                                       eol=eol,
                                       fuzzy_match_header_index=fuzzy_match_header_index,
                                       fuzzy_match_todo_comment=args.fuzzy_match_todo_comment,
                                       src_file_content=src_file_content,
                                       src_filepath=src_filepath):
                    changed_files.append(src_filepath)
            else:
                if license_not_found(remove_header=args.remove_header,
                                     eol=eol,
                                     prefixed_license=prefixed_license,
                                     src_file_content=src_file_content,
                                     src_filepath=src_filepath):
                    changed_files.append(src_filepath)


def license_not_found(remove_header, eol, prefixed_license, src_file_content, src_filepath):
    """
    Executed when license is not found. It either adds license if remove_header is False,
        does nothing if remove_header is True.
    :param remove_header: whether header should be removed if found
    :param eol: end-of-line detected
    :param prefixed_license: license prefixed according to the configuration
    :param src_file_content: content of the src_file
    :param src_filepath: path of the src_file
    :return: True if change was made, False otherwise
    """
    if not remove_header:
        index = 0
        for line in src_file_content:
            stripped_line = line.strip()
            # Special treatment for shebang, encoding and empty lines when at the beginning of the file
            # (adds license only after those)
            if stripped_line.startswith("#!") \
                    or stripped_line.startswith("# -*- coding") \
                    or stripped_line == "":
                index += 1
            else:
                break
        src_file_content = src_file_content[:index] + prefixed_license + [eol] + src_file_content[index:]
        with open(src_filepath, 'w') as src_file:
            src_file.write(''.join(src_file_content))
        return True
    return False


def license_found(remove_header, license_header_index, prefixed_license, src_file_content, src_filepath):
    """
    Executed when license is found. It does nothing if remove_header is False,
        removes the license if remove_header is True.
    :param remove_header: whether header should be removed if found
    :param license_header_index: index where
    :param prefixed_license: license prefixed according to the configuration
    :param src_file_content: content of the src_file
    :param src_filepath: path of the src_file
    :return: True if change was made, False otherwise
    """
    if remove_header:
        if src_file_content[license_header_index + len(prefixed_license)].strip():
            src_file_content = src_file_content[:license_header_index] + \
                               src_file_content[license_header_index + len(prefixed_license):]
        else:
            src_file_content = src_file_content[:license_header_index] + \
                               src_file_content[license_header_index + len(prefixed_license) + 1:]
        with open(src_filepath, 'w') as src_file:
            src_file.write(''.join(src_file_content))
        return True
    return False


def fuzzy_license_found(comment_prefix,
                        eol,
                        fuzzy_match_header_index,
                        fuzzy_match_todo_comment,
                        src_file_content,
                        src_filepath):
    """
    Executed when fuzzy license is found. It inserts comment indicating that the license should be
        corrected.
    :param comment_prefix: prefix for the inserted comment
    :param eol: end of line used
    :param fuzzy_match_header_index: index where
    :param fuzzy_match_todo_comment: comment to add when fuzzy match found
    :param src_file_content: content of the src_file
    :param src_filepath: path of the src_file
    :return: True if change was made, False otherwise
    """
    src_file_content = \
        src_file_content[:fuzzy_match_header_index] + \
        [comment_prefix + fuzzy_match_todo_comment + eol] + \
        src_file_content[fuzzy_match_header_index:]
    with open(src_filepath, 'w') as src_file:
        src_file.write(''.join(src_file_content))
    return True


def find_license_header_index(src_file_content,
                              prefixed_license,
                              top_lines_count):
    """
    Returns the line number, starting from 0 and lower than `top_lines_count`,
    where the license header comment starts in this file, or else None.
    """
    for i in range(top_lines_count):
        license_match = True
        for j, license_line in enumerate(prefixed_license):
            if i + j >= len(src_file_content) or license_line.strip() != src_file_content[i + j].strip():
                license_match = False
                break
        if license_match:
            return i
    return None


def skip_license_insert_or_todo_found(src_file_content,
                                      skip_license_insertion_comment,
                                      fuzzy_match,
                                      fuzzy_match_todo_comment,
                                      top_lines_count):
    """
    Returns True if skip license insert comment is found in top X lines
    """
    for i in range(top_lines_count):
        if i < len(src_file_content) and \
                (skip_license_insertion_comment in src_file_content[i] or
                 fuzzy_match and fuzzy_match_todo_comment in src_file_content[i]):
            return True
    return False


def remove_prefix(text, prefix):
    if text.startswith(prefix):
        return text[len(prefix):]
    return text


def fuzzy_find_license_header_index(src_file_content,
                                    plain_license,
                                    comment_prefix,
                                    top_lines_count,
                                    fuzzy_ratio_cut_off,
                                    num_extra_lines):
    """
    Returns the line number, starting from 0 and lower than `top_lines_count`,
    where the fuzzy matching found best match with ratio higher than the cutoff ration.
    """
    best_match = None
    best_ratio = 0
    license_string = " ".join(plain_license)
    stripped_comment_prefix = comment_prefix.strip()
    for i in range(top_lines_count):
        candidate_array = \
            src_file_content[i:i + len(plain_license) + num_extra_lines + EXTRA_FUZZY_LICENSE_LINES]
        license_string_candidate = get_license_candidate_string(candidate_array, stripped_comment_prefix)
        ratio = fuzz.partial_token_set_ratio(license_string, license_string_candidate)
        if ratio > fuzzy_ratio_cut_off and ratio > best_ratio:
            best_match = i
            best_ratio = ratio
    return best_match


def get_license_candidate_string(candidate_array, stripped_comment_prefix):
    license_string_candidate = ""
    for license_line in candidate_array:
        stripped_line = license_line.strip()
        if stripped_comment_prefix == "" or stripped_line.startswith(stripped_comment_prefix):
            license_string_candidate += stripped_line + " "
        else:
            # end candidate retrieval when it does not start with the comment prefix
            break
    return license_string_candidate


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
