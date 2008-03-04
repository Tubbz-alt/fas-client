#!/usr/bin/python
# -*- coding: utf-8 -*-
#
# Copyright © 2007-2008  Red Hat, Inc. All rights reserved.
#
# This copyrighted material is made available to anyone wishing to use, modify,
# copy, or redistribute it subject to the terms and conditions of the GNU
# General Public License v.2.  This program is distributed in the hope that it
# will be useful, but WITHOUT ANY WARRANTY expressed or implied, including the
# implied warranties of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
# See the GNU General Public License for more details.  You should have
# received a copy of the GNU General Public License along with this program;
# if not, write to the Free Software Foundation, Inc., 51 Franklin Street,
# Fifth Floor, Boston, MA 02110-1301, USA. Any Red Hat trademarks that are
# incorporated in the source code or documentation are not subject to the GNU
# General Public License and may only be used or replicated with the express
# permission of Red Hat, Inc.
#
# Red Hat Author(s): Mike McGrath <mmcgrath@redhat.com>
#
# TODO: put tmp files in a 700 tmp dir

import sys
import logging
import os
import tempfile

from fedora.tg.client import BaseClient, AuthError, ServerError
from optparse import OptionParser
from shutil import move, rmtree
from rhpl.translate import _

import ConfigParser

parser = OptionParser()

parser.add_option('-i', '--install',
                     dest = 'install',
                     default = False,
                     action = 'store_true',
                     help = _('Download and sync most recent content'))
parser.add_option('-c', '--config',
                     dest = 'CONFIG_FILE',
                     default = '/etc/fas.conf',
                     metavar = 'CONFIG_FILE',
                     help = _('Specify config file (default "%default")'))
parser.add_option('--nogroup',
                     dest = 'no_group',
                     default = False,
                     action = 'store_true',
                     help = _('Do not sync group information'))
parser.add_option('--nopasswd',
                     dest = 'no_passwd',
                     default = False,
                     action = 'store_true',
                     help = _('Do not sync passwd information'))
parser.add_option('--noshadow',
                     dest = 'no_shadow',
                     default = False,
                     action = 'store_true',
                     help = _('Do not sync shadow information'))
parser.add_option('-s', '--server',
                     dest = 'FAS_URL',
                     default = None,
                     metavar = 'FAS_URL',
                     help = _('Specify URL of fas server.'))
parser.add_option('-e', '--enable',
                     dest = 'enable',
                     default = False,
                     action = 'store_true',
                     help = _('Enable FAS synced shell accounts'))
parser.add_option('-d', '--disable',
                     dest = 'disable',
                     default = False,
                     action = 'store_true',
                     help = _('Disable FAS synced shell accounts'))

(opts, args) = parser.parse_args()

try:
    config = ConfigParser.ConfigParser()
    if os.path.exists(opts.CONFIG_FILE):
        config.read(opts.CONFIG_FILE)
    elif os.path.exists('fas.conf'):
        config.read('fas.conf')
        print >> sys.stderr, "Could not open %s, defaulting to ./fas.conf" % opts.CONFIG_FILE
    else:
        print >> sys.stderr, "Could not open %s." % opts.CONFIG_FILE
        sys.exit(5)
except ConfigParser.MissingSectionHeaderError, e:
        print >> sys.stderr, "Config file does not have proper formatting - %s" % e
        sys.exit(6)

FAS_URL = config.get('global', 'url')

class MakeShellAccounts(BaseClient):
    temp = None
    groups = None
    people = None
    memberships = None
    
    def mk_tempdir(self):
        self.temp = tempfile.mkdtemp('-tmp', 'fas-', config.get('global', 'temp'))

    def rm_tempdir(self):
        rmtree(self.temp)
        
    def is_valid_user(self, person_id):
        ''' Determine if person is valid on this machine as defined in the
        config file.  I worry that this is going to be horribly inefficient
        with large numbers of users and groups.'''
        for member in self.memberships:
            for group in self.memberships[member]:
                if group['person_id'] == person_id:
                    return True
        return False

    def shadow_text(self, people=None):
        i = 0
        file = open(self.temp + '/shadow.txt', 'w')
        os.chmod(self.temp + '/shadow.txt', 00400)
        if not people:
            people = self.people_list()
        for person in people:
            uid = person['id']
            if self.is_valid_user(uid):
                username = person['username']
                password = person['password']
                file.write("=%i %s:%s:99999:0:99999:7:::\n" % (uid, username, password))
                file.write("0%i %s:%s:99999:0:99999:7:::\n" % (i, username, password))
                file.write(".%s %s:%s:99999:0:99999:7:::\n" % (username, username, password))
                i = i + 1
        file.close()
        
    def passwd_text(self, people=None):
        i = 0
        file = open(self.temp + '/passwd.txt', 'w')
        if not self.people:
            self.people = self.people_list()
        for person in self.people:
            uid = person['id']
            if self.is_valid_user(uid):
                username = person['username']
                human_name = person['human_name']
                home_dir = "%s/%s" % (config.get('users', 'home'), username)
                shell = config.get('users', 'shell')
                file.write("=%s %s:x:%i:%i:%s:%s:%s\n" % (uid, username, uid, uid, human_name, home_dir, shell))
                file.write("0%i %s:x:%i:%i:%s:%s:%s\n" % (i, username, uid, uid, human_name, home_dir, shell))
                file.write(".%s %s:x:%i:%i:%s:%s:%s\n" % (username, username, uid, uid, human_name, home_dir, shell))
                i = i + 1
        file.close()
        
    def groups_text(self, groups=None, people=None):
        i = 0
        file = open(self.temp + '/group.txt', 'w')
        if not groups:
            groups = self.group_list()
        if not people:
            people = self.people_list()
        
        ''' First create all of our users/groups combo '''
        usernames = {}
        for person in people:
            uid = person['id']
            username = person['username']
            usernames[uid] = username
            file.write("=%i %s:x:%i:\n" % (uid, username, uid))
            file.write("0%i %s:x:%i:\n" % (i, username, uid))
            file.write(".%s %s:x:%i:\n" % (username, username, uid))
            i = i + 1
        
        for group in groups:
            gid = group['id']
            name = group['name']
            try:
                ''' Shoot me now I know this isn't right '''
                members = []
                for member in self.memberships[name]:
                    members.append(usernames[member['person_id']])
                memberships = ','.join(members)
            except KeyError:
                ''' No users exist in the group '''
                pass
            file.write("=%i %s:x:%i:%s\n" % (gid, name, gid, self.memberships))
            file.write("0%i %s:x:%i:%s\n" % (i, name, gid, self.memberships))
            file.write(".%s %s:x:%i:%s\n" % (name, name, gid, self.memberships))
            i = i + 1

        file.close()

    def group_list(self, search='*'):
        params = {'search' : search}
        request = self.send_request('group/list', auth=True, input=params)
        self.groups = request['groups']
        self.memberships = request['memberships']
        return self.groups

    def people_list(self, search='*'):
        params = {'search' : search}
        self.people = self.send_request('user/list', auth=True, input=params)['people']
        return self.people

    def make_group_db(self):
        self.groups_text()
        os.system('makedb -o %s/group.db %s/group.txt' % (self.temp, self.temp))

    def make_passwd_db(self):
        self.passwd_text()
        os.system('makedb -o %s/passwd.db %s/passwd.txt' % (self.temp, self.temp))
    
    def make_shadow_db(self):
        self.shadow_text()
        os.system('makedb -o %s/shadow.db %s/shadow.txt' % (self.temp, self.temp))
        os.chmod(self.temp + '/shadow.db', 00400)
    
    def install_passwd_db(self):
        try:
            move(self.temp + '/passwd.db', '/var/db/passwd.db')
        except IOError, e:
            print "ERROR: Could not write passwd db - %s" % e
    
    def install_shadow_db(self):
        try:
            move(self.temp + '/shadow.db', '/var/db/shadow.db')
        except IOError, e:
            print "ERROR: Could not write shadow db - %s" % e
    
    def install_group_db(self):
        try:
            move(self.temp + '/group.db', '/var/db/group.db')
        except IOError, e:
            print "ERROR: Could not write group db - %s" % e

def enable():
    temp = tempfile.mkdtemp('-tmp', 'fas-', config.get('global', 'temp'))

    old = open('/etc/sysconfig/authconfig', 'r')
    new = open(temp + '/authconfig', 'w')
    for line in old:
        if line.startswith("USEDB"):
            new.write("USEDB=yes\n")
        else:
            new.write(line)
    new.close()
    old.close()
    try:
        move(temp + '/authconfig', '/etc/sysconfig/authconfig')
    except IOError, e:
        print "ERROR: Could not write /etc/sysconfig/authconfig - %s" % e
        sys.exit(5)
    os.system('/usr/sbin/authconfig --updateall')
    rmtree(temp)

def disable():
    temp = tempfile.mkdtemp('-tmp', 'fas-', config.get('global', 'temp'))
    old = open('/etc/sysconfig/authconfig', 'r')
    new = open(temp + '/authconfig', 'w')
    for line in old:
        if line.startswith("USEDB"):
            new.write("USEDB=no\n")
        else:
            new.write(line)
    old.close()
    new.close()
    try:
        move(temp + '/authconfig', '/etc/sysconfig/authconfig')
    except IOError, e:
        print "ERROR: Could not write /etc/sysconfig/authconfig - %s" % e
        sys.exit(5)
    os.system('/usr/sbin/authconfig --updateall')
    rmtree(temp)


if __name__ == '__main__':
    if opts.enable:
        enable()
    if opts.disable:
        disable()

    if opts.install:
        try:
            fas = MakeShellAccounts(FAS_URL, config.get('global', 'login'), config.get('global', 'password'), False)
        except AuthError, e:
            print >> sys.stderr, e
            sys.exit(1)
        fas.mk_tempdir()
        fas.make_group_db()
        fas.make_passwd_db()
        fas.make_shadow_db()
        if not opts.no_group:
            fas.install_group_db()
        if not opts.no_passwd:
            fas.install_passwd_db()
        if not opts.no_shadow:
            fas.install_shadow_db()
        fas.rm_tempdir()
    if not (opts.install or opts.enable or opts.disable):
        parser.print_help()
