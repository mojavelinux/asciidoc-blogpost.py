#!/usr/bin/env python
"""
Wordpress command-line weblog client for AsciiDoc.

Copyright: Stuart Rackham (c) 2008
License:   MIT
Email:     srackham@methods.co.nz

"""

VERSION = '0.1.0'

import sys
import os
import time
import subprocess
import StringIO
import traceback
import re
import xmlrpclib

import wordpresslib # http://code.google.com/p/wordpress-library/


######################################################################
# Configuration file parameters.
# Create a separate configuration file named .blogpost in your $HOME
# directory or use the --conf-file option (see the
# blogpost_example.conf example).
# Alternatively you could just edit the values below.
######################################################################

URL = None      # Wordpress XML-RPC URL (don't forget to append /xmlrpc.php)
USERNAME = None # Wordpress login name.
PASSWORD = None # Wordpress password.
ASCIIDOC = None # Path to asciidoc.py (unnecessary if asciidoc is in path).


######################################################################
# End of configuration file parameters.
######################################################################


#####################
# Utility functions #
#####################

class Namespace(object):
    """
    Ad-hoc namespace.
    """
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

def errmsg(msg):
    sys.stderr.write('%s\n' % msg)

def infomsg(msg):
    print msg

def die(msg):
    errmsg('\nERROR: %s' % msg)
    errmsg("       view options with '%s --help'" % os.path.basename(__file__))
    sys.exit(1)

def trace():
    """Print traceback to stderr."""
    errmsg('-'*60)
    traceback.print_exc(file=sys.stderr)
    errmsg('-'*60)

def verbose(msg):
    if OPTIONS.verbose or OPTIONS.dry_run:
        infomsg(msg)

def user_says_yes(prompt, default=None):
    """
    Prompt user to answer yes or no.
    Return True is user answers yes, False if no.
    """
    if default is True:
        prompt += ' [Y/n]:'
    elif default is False:
        prompt += ' [y/N]:'
    else:
        prompt += ' [y/n]:'
    while True:
        print prompt,
        s = raw_input().strip()
        if re.match(r'^[nN]', s):
            result = False
            break
        if re.match(r'^[yY]', s):
            result = True
            break
        if s == '' and default is not None:
            result = default
            break
    print
    return result

def user_input(prompt, pat, default=None):
    """
    Prompt the user for input until it matches regular expression 'pat'.
    """
    while True:
        if default is not None:
            prompt += ' [%s]' % default
        print '%s:' % prompt,
        s = raw_input().strip()
        pat = r'^' + pat + r'$'
        if re.match(pat, s) or (s == '' and default is not None):
            break
    if s == '':
        s = default
    return s

def read_file(filename):
    """Return contents of file."""
    verbose('read file: %s' % filename)
    f = open(filename, 'r')
    try:
        return f.read()
    finally:
        f.close()

def write_file(filename, s=''):
    """Write string to file."""
    verbose('write file: %s: %s' % (filename, s))
    if OPTIONS.dry_run:
        return
    f = open(filename, 'w')
    try:
        f.write(s)
    finally:
        f.close()

def get_module(name, dir, globals={}):
    """
    Import and return module from directory.
    """
    sys.path.append(dir)
    result = __import__(name, globals, {}, [''])
    sys.path.pop()
    return result

def load_conf(conf_file):
    """
    Import optional configuration file which is used to override global
    configuration settings.
    """
    execfile(conf_file, globals())

def exec_args(args, dry_run=False, is_verbose=False):
    verbose('executing: %s' % ' '.join(args))
    if not dry_run:
        if is_verbose:
            stderr = None
        else:
            stderr = subprocess.PIPE
        p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=stderr)
        result = p.communicate()[0]
        if p.returncode != 0:
            raise subprocess.CalledProcessError(p.returncode, ' '.join(args))
    else:
        result = ''
    return result


###########
# Globals #
###########

OPTIONS = None  # Parsed command-line options OptionParser object.


####################
# Application code #
####################

class AppException(Exception): pass

def get_doctitle(filename):
    """
    Return title from AsciiDoc document.
    """
    #TODO: Skip leading comment blocks.
    for line in open(filename):
        # Skip blank lines and comment lines.
        if not re.match(r'(^//)|(^\s*$)', line):
            break
    else:
        die('unable to find document title in %s' % filename)
    return line.strip()

def asciidoc2html(filename):
    """
    Convert AsciiDoc source file to Wordpress compatible HTML string.
    """
    if ASCIIDOC is None:
        asciidoc = 'asciidoc'
    else:
        asciidoc = ASCIIDOC
    return exec_args(
        [
            asciidoc,
            '--no-header-footer',
            '--doctype', OPTIONS.doctype,
            '--backend', 'wordpress',
            '--out-file', '-',
            filename,
        ],
        is_verbose=OPTIONS.verbose)

def html2wordpress(src):
    """
    Convert HTML source file object to and HTML string that plays well
    with Wordpress. This involves removing all line breaks apart from
    those in <pre></pre> blocks.
    """
    result = ''
    for line in src:
        if line.startswith('<pre'):
            while '</pre>' not in line:
                result += line
                line = src.next()
            result += line
        else:
            line = line.strip()
            if result == '' or result.endswith('>') or line.startswith('<'):
                sep = ''
            else:
                sep = ' '
            result += sep + line
    return result

def blog_client():
    """
    Return initialized Wordpress client.
    """
    verbose('wordpress client connection: %s:%s@%s' % (USERNAME, PASSWORD, URL))
    result = wordpresslib.WordPressClient(URL, USERNAME, PASSWORD)
    result.selectBlog(0)
    return result

def get_blog(wp, post_id):
    """
    Return blog post with ID post_id from Wordpress client wp.
    """
    verbose('getting blog post %s...' % post_id)
    if OPTIONS.dry_run:
        post = wordpresslib.WordPressPost() # Stub.
    else:
        if post_id == '.':
            if OPTIONS.page:
                post = wp.getLastPage()
            else:
                post = wp.getLastPost()
            post_id = post.id
        else:
            if OPTIONS.page:
                post = wp.getPage(post_id)
            else:
                post = wp.getPost(post_id)
    return post

def list_blogs():
    """
    List recent blog posts.
    """
    wp = blog_client()
    if OPTIONS.page:
        posts = wp.getRecentPages()
    else:
        posts = wp.getRecentPosts(20)
    for post in posts:
        print '%d: %s: %s' % \
            (post.id, time.strftime('%c', post.date), post.title)

def delete_blog(post_id):
    """
    Delete blog post with ID post_id.
    If post_id == '.' delete most recent post.
    """
    wp = blog_client()
    if post_id == '.':
        post = get_blog(wp, post_id)
        post_id = post.id
    infomsg('deleting blog post %d...' % post_id)
    if not OPTIONS.dry_run:
        if OPTIONS.page:
            if not wp.deletePage(post_id):
                die('failed to delete page %d' % post_id)
        else:
            if not wp.deletePost(post_id):
                die('failed to delete post %d' % post_id)

def post_blog(post_id, blog_file):
    """
    Update an existing Wordpress blog post if post_id is not None,
    else create a new post.
    The blog_file can be either an AsciiDoc file (default) or an
    HTML file (OPTIONS.html == True).
    The OPTIONS.publish value is only used when creating a new blog,
    the publication status of existing blogs is left unchanged.
    """
    wp = blog_client()
    if post_id is not None:
        post = get_blog(wp, post_id)
        post_id = post.id
    else:
        post = wordpresslib.WordPressPost()
    if OPTIONS.title is not None:
        post.title = OPTIONS.title
    if not OPTIONS.html:
        if OPTIONS.title is None:
            post.title = get_doctitle(blog_file)
        content = asciidoc2html(blog_file)
        content = StringIO.StringIO(content)
    else:
        content = open(blog_file)
    post.description = html2wordpress(content)
    verbose('title: %s' % post.title)
    if OPTIONS.verbose:
        # This can be a lot of output so only show if the user asks.
        infomsg('description: %s' % post.description)
    # Create post.
    status = 'published' if OPTIONS.publish else 'unpublished'
    if post_id:
        infomsg('updating blog post %s...' % post_id)
    else:
        infomsg('creating %s blog post...' % status)
    if not OPTIONS.dry_run:
        if post_id is None:
            if OPTIONS.page:
                post_id = wp.newPage(post, OPTIONS.publish)
            else:
                post_id = wp.newPost(post, OPTIONS.publish)
        else:
            if OPTIONS.page:
                wp.editPage(post_id, post, OPTIONS.publish)
            else:
                wp.editPost(post_id, post, OPTIONS.publish)
        print 'id: %s' % post_id


if __name__ == "__main__":
    description = """Wordpress command-line weblog client for AsciiDoc. COMMAND can be one of: create, delete, list, update. POST_ID is blog post ID number (or . for most recent post). BLOG_FILE is AsciiDoc text file."""
    from optparse import OptionParser
    parser = OptionParser(usage='usage: %prog [OPTIONS] COMMAND [POST_ID] [BLOG_FILE]',
        version='%prog ' + VERSION,
        description=description)
    parser.add_option('-f', '--conf-file',
        dest='conf_file', default=None, metavar='CONF_FILE',
        help='configuration file')
    parser.add_option('-p', '--publish',
        action='store_true', dest='publish', default=False,
        help='set blog post status to published')
    parser.add_option('--html',
        action='store_true', dest='html', default=False,
        help='BLOG_FILE is an HTML file not an AsciiDoc file')
    if 'getPage' in dir(wordpresslib.WordPressClient):
        # We have patched wordpresslib module so enable --page option.
        parser.add_option('--page',
            action='store_true', dest='page', default=False,
            help='apply command to weblog pages')
    else:
        OPTIONS.__dict__['page'] = False
    parser.add_option('-t', '--title',
        dest='title', default=None, metavar='TITLE',
        help='blog post title')
    parser.add_option('-d', '--doctype',
        dest='doctype', default='article', metavar='DOCTYPE',
        help='Asciidoc document type (article, book, manpage')
    parser.add_option('-n', '--dry-run',
        action='store_true', dest='dry_run', default=False,
        help='show what would have been done')
    parser.add_option('-v', '--verbose',
        action='store_true', dest='verbose', default=False,
        help='increase verbosity')
    if len(sys.argv) == 1:
        parser.parse_args(['--help'])
    OPTIONS, args = parser.parse_args()
    # Validate options and command arguments.
    if len(args) not in (1,2,3):
        die('too few or too many arguments')
    command = args[0]
    short_commands = {'c':'create', 'd':'delete', 'l':'list', 'u':'update'}
    if command in short_commands.keys():
        command = short_commands[command]
    if command not in ('create','delete','list','update'):
        die('illegal command: %s' % command)
    args_len = {'create':2, 'delete':2, 'list':1, 'update':3}
    if len(args) != args_len[command]:
        die('too few or too many arguments')
    blog_file = None
    post_id = None
    if command == 'create':
        blog_file = args[1]
    elif command == 'delete':
        post_id = args[1]
    elif command == 'update':
        post_id = args[1]
        blog_file = args[2]
    if blog_file is not None:
        if not os.path.isfile(blog_file):
            die('BLOG_FILE not found: %s' % blog_file)
        blog_file = os.path.abspath(blog_file)
    if post_id is not None:
        if post_id != '.':
            try:
                post_id = int(post_id)
            except ValueError:
                die('invalid POST_ID: %s' % post_id)
    if OPTIONS.doctype not in ('article','book','manpage'):
        die('ivalid DOCTYPE: %s' % OPTIONS.doctype)
    # If conf file exists in $HOME directory load it.
    home_dir = os.environ.get('HOME')
    if home_dir is not None:
        conf_file = os.path.join(home_dir, '.blogpost')
        if os.path.isfile(conf_file):
            load_conf(conf_file)
    if OPTIONS.conf_file is not None:
        if not os.path.isfile(OPTIONS.conf_file):
            die('configuration file not found: %s' % OPTIONS.conf_file)
        load_conf(OPTIONS.conf_file)
    # Validate configuration file parameters.
    if URL is None:
        die('Wordpress XML-RPC URL has not been set in configuration file')
    if USERNAME is None:
        die('Wordpress USERNAME has not been set in configuration file')
    if PASSWORD is None:
        die('Wordpress PASSWORD has not been set in configuration file')
    # Do the work.
    try:
        if command == 'list':
            list_blogs()
        elif command == 'delete':
            delete_blog(post_id)
        else:
            post_blog(post_id, blog_file)
    except (wordpresslib.WordPressException, xmlrpclib.ProtocolError), e:
        msg = e.message
        if not msg:
            # xmlrpclib.ProtocolError does not set message attribute.
            msg = e
        die(msg)

