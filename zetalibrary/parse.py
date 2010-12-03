""" Base zeta linker.
"""
import optparse
import os.path
import re
import sys
import urllib2

import cssmin


BASEDIR = os.path.realpath(os.path.dirname(__file__))
ZETALIBDIR = os.path.join(BASEDIR, 'zetalib')


FORMATS = dict(
    css = dict(
        import_template = re.compile( r'^\@import +url\(\s*["\']?([^\)\'\"]+)["\']?\s*\)\s*;?\s*$', re.MULTILINE),
        comment_template = '/* %s */\n',
        link_parse = re.compile(r'url\(\s*["\']?([^\)\'\"]+)["\']?\)'),
        link_ignore = ('data:image', 'http://', 'https://'),
        remove_comments = cssmin.remove_comments,
    ),
    js = dict(
        import_template = re.compile(r'^require\([\'\"]([^\'\"]+)[\'\"]\)\s*;+\s*$', re.MULTILINE),
        comment_template = '// %s\n',
        remove_comments = lambda x: '\n'.join([l for l in x.split('\n') if not l.strip().startswith('//')]),
    )
)


class LinkerError( Exception ):
    """Linker error.
    """
    def __init__( self, message, parent=None ):
        if parent:
            message = "%s: %s" % (parent, message)
        super( LinkerError, self ).__init__( message )


class Linker( object ):
    """ Link js and css files in to one.
    """
    def __init__(self, path, prefix='_', no_comments=False):
        self.path = path
        self.no_comments = no_comments
        self.prefix = prefix
        self.imported = set()
        self.tree = list()
        self.basedir = os.path.relpath( os.path.dirname( path ))
        self.curfile = None

        filetype = os.path.splitext(path)[1][1:] or ''
        try:
            self.params = FORMATS[filetype]
        except KeyError:
            raise LinkerError("Unknow format file: '%s'" % path)

    def link( self ):
        """ Parse and save file.
        """
        self.out("Packing '%s'." % self.path)
        self.parse_tree(self.path)
        out = ''
        for item in self.tree:
            src = item['src'].strip()
            if not src:
                continue
            out += "".join([
                self.params['comment_template'] % ("=" * 30),
                self.params['comment_template'] % "Zeta import: '%s'" % item['current'],
                self.params['comment_template'] % "From: '%s'" % item['parent'],
                src,
                "\n\n\n",
            ])

        pack_name = self.prefix + os.path.basename(self.path)
        pack_path = os.path.join(self.basedir, pack_name)
        try:
            open(pack_path, 'w').write(out)
            self.out("Linked file saved as: '%s'." % pack_path)
        except IOError, ex:
            raise LinkerError(ex)

    def parse_tree( self, path, parent=None ):
        """ Parse import structure.
        """
        try:
            src = self.open_path(path).read()
        except IOError, ex:
            raise LinkerError(ex, parent)

        curdir = os.path.relpath(os.path.normpath(os.path.dirname(path)))

        def children( obj ):
            """ Regexp search.
            """
            child_path = self.parse_path(obj.group(1), curdir)
            try:
                if child_path in self.imported:
                    self.out("%s: %s already imported." % (path, child_path))
                    return
                self.imported.add(path)
                self.parse_tree(child_path, path)
            except OSError:
                self.out("%s: import file '%s' does not exist." % (path, child_path), error=True)

        src = self.params['import_template'].sub(children, src)

        if self.params.get('link_parse'):
            src = self.link_parse(src, curdir)

        if self.no_comments and self.params.get('remove_comments'):
            src = self.params['remove_comments'](src)
        self.tree.append(dict(src=src, parent=parent, current=path))

    def parse_path(self, path, curdir):
        """ Parse path.
        """
        if path.startswith('http://'):
            return path

        elif path.startswith('/'):
            return os.path.relpath(os.path.normpath(os.path.join(self.basedir, path)))

        elif path.startswith('zeta://'):
            path = path[7:]
            return os.path.relpath(os.path.normpath(os.path.join(ZETALIBDIR, path)))

        return os.path.relpath(os.path.normpath(os.path.join(curdir, path)))

    def link_parse(self, src, curdir):
        """ Parse links.
        """
        def parse( obj ):
            """ Regexp search.
            """
            link = obj.group(0)
            path = obj.group(1)
            if self.params.get('link_ignore'):
                for ignore in self.params['link_ignore']:
                    if path.startswith(ignore):
                        return link
            try:
                return link.replace(path, os.path.relpath(os.path.join(curdir, path), self.basedir))
            except OSError:
                self.out('Url error: [%s] -- %s' % (curdir, path), error=True)

        return self.params['link_parse'].sub(parse, src)

    def open_path(self, path):
        """ Read source.
        """
        if path.startswith('http://'):
            name = os.path.basename(path)
            import_path = os.path.join(self.basedir, name)
            if not os.path.exists(import_path):
                src = urllib2.urlopen(path).read()
                open(import_path, 'w').write(src)

            path = import_path
        return open(path, 'r')

    @staticmethod
    def out( message, error=False ):
        """ Out messages.
        """
        pipe = sys.stdout if not error else sys.stderr
        pipe.write("\n  * %s\n" % message)


def route( path, prefix='_' ):
    """ Route files.
    """
    def test_file( filepath ):
        """ Test file is static and not parsed.
        """
        name, ext = os.path.splitext(os.path.basename(filepath))
        filetype = ext[1:]
        return os.path.isfile(filepath) and not name.startswith(prefix) and filetype in FORMATS.keys()

    if os.path.isdir( path ):
        for name in os.listdir(path):
            filepath = os.path.join(path, name)
            if test_file(filepath):
                yield filepath

    elif test_file(filepath):
        yield filepath


def main():
    """ Parse arguments.
    """
    parser = optparse.OptionParser(
        usage="%prog [--prefix PREFIX] FILENAME or DIRNAME",
        description="Parse file or dir, import css, js code and save with prefix.")

    parser.add_option(
        '-p', '--prefix', default='_', dest='prefix',
        help="Save result with prefix. Default is '_'.")

    parser.add_option(
        '-n', '--no-comments', action='store_true', dest='no_comments',
        help="Save result with prefix. Default is '_'.")

    options, args = parser.parse_args()
    if len(args) != 1:
        parser.error("Wrong number of arguments.")

    path = args[0]
    try:
        assert os.path.exists(path)
    except AssertionError:
        parser.error("'%s' does not exist." % args[0])

    for path in route(path, options.prefix):
        try:
            linker = Linker(path, options.prefix, options.no_comments)
            linker.link()
        except LinkerError, ex:
            parser.error(ex)