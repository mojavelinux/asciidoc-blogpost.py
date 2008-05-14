#!/usr/bin/env python
"""
A utility for posting AsciiDoc documents to Wordpress blog.

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

import wordpresslib


######################################################################
# Default configuration parameters.
# To override the parameters
# create a separate configuration file (see --conf-file option).
######################################################################

URL = None  # Wordpress XML_RPC URL (don't forget to append /xmlrpc.php)
USERNAME = None   # Wordpress login name.
PASSWORD = None # Wordpress password.


######################################################################
# End of configuration parameters.
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

def exec_args(args):
    verbose('executing: %s' % ' '.join(args))
    if not OPTIONS.dry_run:
        if OPTIONS.verbose:
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
# Temp stub object.
OPTIONS = Namespace(verbose=False, dry_run=False)


####################
# Application code #
####################

class AppException(Exception): pass

def get_doctitle(filename):
    """
    Return title from AsciiDoc document.
    """
    title = open(filename).readline().strip()
    return title

def asciidoc2html(filename):
    """
    Convert AsciiDoc source file to Wordpress compatible HTML.
    """
    return exec_args(
        [
            'asciidoc',
            '--conf-file', 'asciidoc_wordpress.conf',
            '--no-header-footer',
            '--backend', 'html4',
            '--out-file', '-',
            filename,
        ])

def html2wordpress(src):
    """
    Convert HTML source file object to and HTML string that plays well
    with Wordpress. This involves removing all line breaks apart from
    those in <pre></pre> blocks.
    """
    result = ''
    sep = ''
    for line in src:
        if line.startswith('<pre'):
            while '</pre>' not in line:
                result += line
                line = src.next()
            result += line
            sep = ''
        else:
            result += sep + line.strip()
            sep = ' '
    return result

def blog_client():
    """
    Return initialized Wordpress client.
    """
    verbose('wordpress client: %s:%s@%s' % (USERNAME, PASSWORD, URL))
    result = wordpresslib.WordPressClient(URL, USERNAME, PASSWORD)
    result.selectBlog(0)
    return result

def list_blogs():
    wp = blog_client()
    for post in wp.getRecentPosts(20):
        print '%d: %s: %s' % \
            (post.id, time.strftime('%c', post.date), post.title)

def post_blog():
    """
    Update an existing Wordpress blog post if OPTIONS.post_id is not None,
    else create a new post.
    The OPTIONS.publish value is only used when creating a new blog,
    the publication status of existing blogs is left unchanged.
    """
    wp = blog_client()
    if OPTIONS.post_id:
        verbose('getting blog post %s...' % OPTIONS.post_id)
        if OPTIONS.dry_run:
            post = wordpresslib.WordPressPost() # Stub.
        else:
            if OPTIONS.post_id == '.':
                post = wp.getLastPost()
                OPTIONS.post_id = post.id
            else:
                post = wp.getPost(OPTIONS.post_id)
    else:
        post = wordpresslib.WordPressPost()
    if OPTIONS.title is not None:
        post.title = OPTIONS.title
    if not OPTIONS.html:
        if OPTIONS.title is None:
            post.title = get_doctitle(OPTIONS.blog_file)
        content = asciidoc2html(OPTIONS.blog_file)
        content = StringIO.StringIO(content)
    else:
        content = open(OPTIONS.blog_file)
    post.description = html2wordpress(content)
    verbose('title: %s' % post.title)
    verbose('description: %s' % post.description)
    # Create post.
    status = 'published' if OPTIONS.publish else 'unpublished'
    if OPTIONS.post_id:
        verbose('updating blog post %s...' % OPTIONS.post_id)
    else:
        verbose('creating %s blog post...' % status)
    if not OPTIONS.dry_run:
        if OPTIONS.post_id is None:
            post_id = wp.newPost(post, OPTIONS.publish)
        else:
            # Setting publish to False ensures the publication status is left unchanged.
            wp.editPost(OPTIONS.post_id, post, False)
            post_id = OPTIONS.post_id
        print 'post_id: %s' % post_id


if __name__ == "__main__":
    description = """Create or update a Wordpress blog post from AsciiDoc or HTML BLOG_FILE"""
    from optparse import OptionParser
    parser = OptionParser(usage='usage: %prog [OPTIONS] [BLOG_FILE]',
        version='%prog ' + VERSION,
        description=description)
    parser.add_option('-f', '--conf-file',
        dest='conf_file', default=None, metavar='CONF_FILE',
        help='configuration file')
    parser.add_option('-p', '--publish',
        action='store_true', dest='publish', default=False,
        help='set blog post status to published')
    parser.add_option('-l', '--list',
        action='store_true', dest='list', default=False,
        help='list recent blog posts then exit')
    parser.add_option('--html',
        action='store_true', dest='html', default=False,
        help='BLOG_FILE is an HTML file not an AsciiDoc file')
    parser.add_option('-t', '--title',
        dest='title', default=None, metavar='TITLE',
        help='blog post title')
    parser.add_option('-i', '--post-id',
        dest='post_id', default=None, metavar='POST_ID',
        help='id of blog post to be updated (. for most recent)')
    parser.add_option('-n', '--dry-run',
        action='store_true', dest='dry_run', default=False,
        help='show what would have been done')
    parser.add_option('-v', '--verbose',
        action='store_true', dest='verbose', default=False,
        help='increase verbosity')
    if len(sys.argv) == 1:
        parser.parse_args(['--help'])
    OPTIONS, args = parser.parse_args()
    # Validate arguments.
    if len(args) > 1:
        die('too many arguments')
    elif len(args) == 1:
        blog_file = args[0]
        if not os.path.isfile(blog_file):
            die('BLOG_FILE not found: %s' % blog_file)
        blog_file = os.path.abspath(blog_file)
        OPTIONS.__dict__['blog_file'] = blog_file
    else:
        if not OPTIONS.list:
            die('must specify BLOG_FILE argument or --list option')
    if OPTIONS.post_id not in ('.', None):
        try:
            OPTIONS.post_id = int(OPTIONS.post_id)
        except ValueError:
            die('invalid --post-id: %s' % OPTIONS.post_id)
    # Read configuration file(s).
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
    # Validate command options.
    if URL is None:
        die('Wordpress XML-RPC URL has not been set in configuration file')
    if USERNAME is None:
        die('Wordpress USERNAME has not been set in configuration file')
    if PASSWORD is None:
        die('Wordpress PASSWORD has not been set in configuration file')
    # Do the work.
    if OPTIONS.list:
        list_blogs()
    else:
        post_blog()
