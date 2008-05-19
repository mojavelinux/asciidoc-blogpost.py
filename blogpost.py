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
import pickle
import md5
import calendar

import wordpresslib # http://www.blackbirdblog.it/programmazione/progetti/28


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
ASCIIDOC = ['asciidoc'] # Arguments to start asciidoc.


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

class BlogpostException(Exception): pass

class Media(object):

    def __init__(self, filename):
        self.filename = filename # Client file name.
        self.checksum = None     # Client file MD5 checksum.
        self.url = None          # WordPress media file URL.

    def upload(self, blog):
        """
        Upload media file to WordPress server if it is new or has changed.
        """
        checksum = md5.new(open(self.filename).read()).hexdigest()
        if self.checksum is not None and self.checksum == checksum:
            verbose('media unchanged: %s' % self.filename)
        else:
            infomsg('uploading: %s...' % self.filename)
            if not blog.options.dry_run:
                self.url =  blog.server.newMediaObject(self.filename)
                print 'url: %s' % self.url
            else:
                self.url = self.filename  # Dummy value for debugging.
            self.checksum = checksum


class Blogpost(object):

    def __init__(self, server_url, username, password, options):
        # options contains the command-line options attributes.
        self.options = options
        # Server-side blog parameters.
        self.url = None
        self.id = None
        self.title = None
        self.status = None  # Publication status ('published','unpublished').
        self.post_type = None   # 'post' or 'page'.
        self.created_at = None  # Seconds since epoch in UTC.
        self.updated_at = None  # Seconds since epoch in UTC.
        self.media = {}  # Contains Media objects keyed by document src path.
        # Client-side blog data.
        self.blog_file = None
        self.checksum = None    # self.blog_file MD5 checksum.
        self.cache_file = None  # Cache file containing persistant blog data.
        self.media_dir = None
        self.content = None     # File-like object containing blog content.
        # XML-RPC server.
        self.server = None              # wordpresslib.WordPressClient.
        self.server_url = server_url    # WordPress XML-RPC server URL.
        self.username = username        # WordPress account user name.
        self.password = password        # WordPress account password.
        verbose('wordpress server: %s:%s@%s' %
                (self.username, self.password, self.server_url))
        self.server = wordpresslib.WordPressClient(
                self.server_url, self.username, self.password)
        self.server.selectBlog(0)

    def is_page(self):
        return self.post_type == 'page'

    def set_blog_file(self, blog_file):
        if blog_file is not None:
            self.blog_file = blog_file
            self.media_dir = os.path.abspath(os.path.dirname(blog_file))
            self.cache_file = os.path.splitext(blog_file)[0] + '.blogpost'

    def set_title_from_blog_file(self):
        """
        Set title attribute from title in blog file.
        """
        if not self.options.html:
            # AsciiDoc blog file.
            #TODO: Skip leading comment blocks.
            for line in open(self.blog_file):
                # Skip blank lines and comment lines.
                if not re.match(r'(^//)|(^\s*$)', line):
                    break
            else:
                die('unable to find document title in %s' % self.blog_file)
            self.title = line.strip()

    def asciidoc2html(self):
        """
        Convert AsciiDoc blog_file to Wordpress compatible HTML content.
        """
        result = exec_args(
            ASCIIDOC +
            [
                '--no-header-footer',
                '--doctype', self.options.doctype,
                '--backend', 'wordpress',
                '--out-file', '-',
                self.blog_file,
            ],
            is_verbose=self.options.verbose)
        self.content = StringIO.StringIO(result)

    def sanitize_html(self):
        """
        Convert HTML content to HTML that plays well with Wordpress.
        This involves removing all line breaks apart from those in
        <pre></pre> blocks.
        """
        result = ''
        for line in self.content:
            if line.startswith('<pre'):
                while '</pre>' not in line:
                    result += line
                    line = self.content.next()
                result += line
            else:
                result += ' ' + line.strip()
        self.content = StringIO.StringIO(result)

    def load_cache(self):
        """
        Load cache file and update self with cache data.
        """
        if self.cache_file is not None and os.path.isfile(self.cache_file):
            verbose('reading cache: %s' % self.cache_file)
            cache = pickle.load(open(self.cache_file))
            self.url = cache.url
            self.id = cache.id
            self.title = cache.title
            self.status = cache.status
            self.post_type = cache.post_type
            self.created_at = cache.created_at
            self.updated_at = cache.updated_at
            self.media = cache.media
            self.checksum = cache.checksum

    def save_cache(self):
        """
        Write cache file.
        """
        if self.cache_file is not None:
            verbose('writing cache: %s' % self.cache_file)
            if not self.options.dry_run:
                cache = Namespace(
                        url = self.url,
                        id = self.id,
                        title = self.title,
                        status = self.status,
                        post_type = self.post_type,
                        created_at = self.created_at,
                        updated_at = self.updated_at,
                        media = self.media,
                        checksum = self.checksum,
                    )
                f = open(self.cache_file, 'w')
                try:
                    pickle.dump(cache, f)
                finally:
                    f.close()

    def delete_cache(self):
        """
        Delete cache file.
        """
        if self.cache_file is not None and os.path.isfile(self.cache_file):
            infomsg('deleting cache file: %s' % self.cache_file)
            if not self.options.dry_run:
                os.unlink(self.cache_file)

    def process_media(self):
        """
        Upload images referenced in the HTML content and replace content urls
        with WordPress urls.

        Source urls are considered relative to self.media_dir.
        Assumes maximum of one <img> per line -- this is true of AsciiDoc
        outputs.

        Caches the names and checksum of uploaded files in self.cache_file.  If
        self.cache_file is None then caching is not used and no cache file
        written.
        """
        result = StringIO.StringIO()
        rexp = re.compile(r'<img src="(.*?)"')
        for line in self.content:
            mo = rexp.search(line)
            if mo:
                src = mo.group(1)
                media_obj = self.media.get(src)
                media_file = os.path.join(self.media_dir, src)
                if not os.path.isfile(media_file):
                    if media_obj:
                        url =  media_obj.url
                    else:
                        url = src
                    errmsg('WARNING: missing media file: %s' % media_file)
                else:
                    if not media_obj:
                        media_obj = Media(media_file)
                        self.media[src] = media_obj
                    media_obj.upload(self)
                    url =  media_obj.url
                line = rexp.sub('<img src="%s"' % url, line)
            result.write(line)
        result.seek(0)
        self.content = result

    def get_post(self):
        """
        Return  wordpresslib.WordPressPost with ID self.id from Wordpress
        server.
        Sets self.id, self.title, self.created_at.
        """
        verbose('getting %s %s...' % (self.post_type, self.id))
        if self.options.dry_run:
            post = wordpresslib.WordPressPost() # Stub.
        else:
            if self.is_page():
                post = self.server.getPage(self.id)
            else:
                post = self.server.getPost(self.id)
        self.id = post.id
        self.title = post.title
        # UTC struct_time to UTC timestamp.
        self.created_at = calendar.timegm(post.date)
        return post

    def info(self):
        """
        Print blog cache information.
        """
        print 'title:   %s' % self.title
        print 'id:      %s' % self.id
        print 'url:     %s' % self.url
        print 'status:  %s' % self.status
        print 'type:    %s' % self.post_type
        print 'created: %s' % time.strftime('%c',
                time.localtime(self.created_at))
        print 'updated: %s' % time.strftime('%c',
                time.localtime(self.updated_at))
        for media_obj in self.media.values():
            print 'media:   %s' % media_obj.url

    def list(self):
        """
        List recent posts.
        Information from WordPress server not from client-side cache.
        """
        if self.is_page():
            posts = self.server.getRecentPages()
        else:
            posts = self.server.getRecentPosts(20)
        for post in posts:
            print 'title:   %s' % post.title
            print 'id:      %s' % post.id
            print 'type:    %s' % self.post_type
            print 'url:     %s' % post.permaLink
            # Convert UTC to local time.
            print 'created: %s' % \
                time.strftime('%c', time.localtime(calendar.timegm(post.date)))
            print
            """
            print '%d: %s: %s: %s' % (
                post.id,
                # Convert UTC to local time.
                time.strftime('%c', time.localtime(calendar.timegm(post.date))),
                post.title,
                post.permaLink,
            )
            """

    def delete(self):
        """
        Delete post with ID self.id.
        """
        assert(self.id is not None)
        infomsg('deleting post %d...' % self.id)
        if not self.options.dry_run:
            if self.is_page():
                if not self.server.deletePage(self.id):
                    die('failed to delete page %d' % self.id)
            else:
                if not self.server.deletePost(self.id):
                    die('failed to delete post %d' % self.id)
        self.delete_cache()

    def create(self):
        assert(self.id is None)
        self.post()

    def update(self):
        assert(self.id is not None)
        self.post()

    def post(self):
        """
        Update an existing Wordpress post if post_id is not None,
        else create a new post.
        The blog_file can be either an AsciiDoc file (default) or an
        HTML file (self.options.html == True).
        """
        # Only update if blog file has changed.
        checksum = md5.new(open(self.blog_file).read()).hexdigest()
        if self.checksum is not None and self.checksum == checksum:
            verbose('blog file unchanged: %s' % self.blog_file)
        self.checksum = checksum
        # Create wordpresslib.WordPressPost object.
        if self.id is not None:
            post = self.get_post()
            self.updated_at = int(time.time())
        else:
            post = wordpresslib.WordPressPost()
            self.created_at = int(time.time())
            self.updated_at = self.created_at
        # Set post title.
        if self.options.title is not None:
            self.title = self.options.title
        if self.options.html:
            if not self.title:
                die('missing title: use --title option')
        else:
            # AsciiDoc blog file.
            if self.options.title is None:
                self.set_title_from_blog_file()
        post.title = self.title
        assert(self.title)
        # Generate blog content from blog file.
        if self.options.html:
            self.content = open(self.blog_file)
        else:
            self.asciidoc2html()
        # Conditionally upload media files.
        if self.options.media:
            self.process_media()
        # Make HTML WordPress friendly.
        self.sanitize_html()
        post.description = self.content.read()
        if self.options.verbose:
            # This can be a lot of output so only show if the user asks.
            infomsg(post.description)
        # Create/update post.
        status = 'published' if self.options.publish else 'unpublished'
        action = 'updating' if self.id else 'creating'
        infomsg("%s %s %s '%s'..." % \
                (action, status, self.post_type, self.title))
        if not self.options.dry_run:
            if self.id is None:
                if self.is_page():
                    self.id = self.server.newPage(post, self.options.publish)
                else:
                    self.id = self.server.newPost(post, self.options.publish)
            else:
                if self.is_page():
                    self.server.editPage(self.id, post, self.options.publish)
                else:
                    self.server.editPost(self.id, post, self.options.publish)
        print 'id: %s' % self.id
        if post.permaLink:
            print 'url: %s' % post.permaLink
            self.url = post.permaLink
        self.status = status
        self.save_cache()


if __name__ != '__main__':
    # So we can import and use as a library.
    OPTIONS = Namespace(
                title = None,
                publish = True,
                pages = False,
                html = False,
                doctype = 'article',
                dry_run = False,
                verbose = False,
                media = True,
                post_id = None,
            )
else:
    long_commands = ('create','delete','info','list','reset','update')
    short_commands = {'c':'create', 'd':'delete', 'i':'info', 'l':'list', 'r':'reset', 'u':'update'}
    description = """A Wordpress command-line weblog client for AsciiDoc. COMMAND can be one of: %s. BLOG_FILE is AsciiDoc (or optionally HTML) text file. POST_ID is optional weblog post ID number.""" % ', '.join(long_commands)
    from optparse import OptionParser
    parser = OptionParser(usage='usage: %prog [OPTIONS] COMMAND [BLOG_FILE]',
        version='%prog ' + VERSION,
        description=description)
    parser.add_option('-f', '--conf-file',
        dest='conf_file', default=None, metavar='CONF_FILE',
        help='configuration file')
    parser.add_option('-u', '--unpublish',
        action='store_false', dest='publish', default=True,
        help='set post status to unpublished')
    parser.add_option('--html',
        action='store_true', dest='html', default=False,
        help='BLOG_FILE is an HTML file (not an AsciiDoc file)')
    if hasattr(wordpresslib.WordPressClient, 'getPage'):
        # We have patched wordpresslib module so enable --pages option.
        parser.add_option('-p', '--pages',
            action='store_true', dest='pages', default=False,
            help='apply COMMAND to weblog pages')
    parser.add_option('-t', '--title',
        dest='title', default=None, metavar='TITLE',
        help='set post TITLE (defaults to document or cache title)')
    parser.add_option('-d', '--doctype',
        dest='doctype', default='article', metavar='DOCTYPE',
        help='Asciidoc document type (article, book, manpage)')
    parser.add_option('-M', '--no-media',
        action='store_false', dest='media', default=True,
        help='do not process document media objects')
    parser.add_option('--post-id', type='int',
        dest='post_id', default=None, metavar='POST_ID',
        help='blog post ID number')
    parser.add_option('-n', '--dry-run',
        action='store_true', dest='dry_run', default=False,
        help='show what would have been done')
    parser.add_option('-v', '--verbose',
        action='store_true', dest='verbose', default=False,
        help='increase verbosity')
    if len(sys.argv) == 1:
        parser.parse_args(['--help'])
    OPTIONS, args = parser.parse_args()
    if not hasattr(wordpresslib.WordPressClient, 'getPage'):
        OPTIONS.__dict__['pages'] = False
    # Validate options and command arguments.
    command = args[0]
    if command in short_commands.keys():
        command = short_commands[command]
    if command not in long_commands:
        parser.error('invalid command: %s' % command)
    blog_file = None
    if len(args) == 1 and command in ('delete','list'):
        # No command arguments.
        pass
    elif len(args) == 2 and command in ('create','delete','info','reset','update'):
        # Single command argument BLOG_FILE
        blog_file = args[1]
    else:
        parser.error('too few or too many arguments')
    if blog_file is not None:
        if not os.path.isfile(blog_file):
            die('missing BLOG_FILE: %s' % blog_file)
        blog_file = os.path.abspath(blog_file)
    if OPTIONS.doctype not in ('article','book','manpage'):
        parser.error('invalid DOCTYPE: %s' % OPTIONS.doctype)
    # --post-id option checks.
    if command not in ('delete','update') and OPTIONS.post_id is not None:
        parser.error('--post-id is incompatible with %s command' % command)
    if command == 'delete':
        if blog_file is None and OPTIONS.post_id is None:
            parser.error('specify the BLOG_FILE or use --post-id option')
        elif blog_file is not None and OPTIONS.post_id is not None:
            parser.error('specify the BLOG_FILE or use --post-id option but not both')
    # If conf file exists in $HOME directory load it.
    home_dir = os.environ.get('HOME')
    if home_dir is not None:
        conf_file = os.path.join(home_dir, '.blogpost')
        if os.path.isfile(conf_file):
            load_conf(conf_file)
    if OPTIONS.conf_file is not None:
        if not os.path.isfile(OPTIONS.conf_file):
            die('missing configuration file: %s' % OPTIONS.conf_file)
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
        blog = Blogpost(URL, USERNAME, PASSWORD, OPTIONS)
        blog.set_blog_file(blog_file)
        blog.load_cache()
        if OPTIONS.post_id is not None:
            blog.id = OPTIONS.post_id
        if OPTIONS.pages:
            blog.post_type = 'page'
        if blog.post_type is None:
            blog.post_type = 'post' # Default if not in cache.
        if command == 'reset':
            if not os.path.isfile(blog.cache_file):
                die('missing cache file: %s' % blog.cache_file)
            blog.delete_cache()
        elif command == 'info':
            if not os.path.isfile(blog.cache_file):
                die('missing cache file: %s' % blog.cache_file)
            blog.info()
        elif command == 'list':
            blog.list()
        elif command == 'delete':
            if blog.id is None:
                die('missing cache file: specify --post-id instead')
            blog.delete()
        elif command == 'create':
            if blog.id is not None:
                die('''document has been previously posted:
       use update command (or reset command followed by create command)''')
            blog.create()
        elif command == 'update':
            if blog.id is None:
                die('missing cache file: specify --post-id instead')
            blog.update()
        else:
            assert(False)
    except (wordpresslib.WordPressException, xmlrpclib.ProtocolError), e:
        msg = e.message
        if not msg:
            # xmlrpclib.ProtocolError does not set message attribute.
            msg = e
        die(msg)

