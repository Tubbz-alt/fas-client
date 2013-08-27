#!/usr/bin/python
# -*- coding: utf-8 -*-
#
# Copyright © 2013  Red Hat, Inc.
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
# Author(s): Xavier Lamien <laxathom@fedoraproject.org>

import os
import logging
import ConfigParser

import pwd
import sys
import codecs
import tempfile
import logging
import syslog

try:
    import selinux
    from shutil import rmtree
    from selinux import copytree, install as move
    have_selinux = (selinux.is_selinux_enabled() == 1)
except ImportError:
    from shutil import move, rmtree, copytree
    have_selinux = False

from sh import makedb, authconfig
from path import path


def read_config(filename='./fas.conf'):
    log = logging.getLogger(__name__)
    try:
        config = ConfigParser.ConfigParser()
        if os.path.exists(filename):
            config.read(filename)
        elif os.path.exists('fas.conf'):
            config.read('fas.conf')
            log.info('Could not open %s, defaulting to ./fas.conf' % filename)
        else:
            log.error('Could not open %s' % filename)
            sys.exit(5)
    except ConfigParser.MissingSectionHeaderError, e:
            log.error('Config file does not have proper formatting: %s' % e)
            sys.exit(6)
    return config

def make_aliases_text():
    '''Create the aliases file'''
    email_file = codecs.open(os.path.join(self.temp, 'aliases'), mode='w', encoding='utf-8')
    email = path(self.temp).files('aliases')
    recipient_file = codecs.open(os.path.join(self.temp, 'relay_recipient_maps'), mode='w', encoding='utf-8')
    recipient = path(self.temp).files('relay_recipient_maps')
    try:
        email_template = codecs.open(config.get('host', 'aliases_template').strip('"'))
    except IOError, e:
        print >> sys.stderr, 'Could not open aliases template %s: %s' % (config.get('host', 'aliases_template').strip('"'), e)
        print >> sys.stderr, 'Aborting.'
        sys.exit(1)

    email_file.write('# Generated by fasClient\n')
    for line in email_template.readlines():
        email_file.write(line)
 
    email_template.close()
 
    username_email = []
    for uid in self.good_users:
        if self.users[uid]['alias_enabled']:
            username_email.append( (self.users[uid]['username'], self.users[uid]['email']) )
        else:
            recipient_file.write('%s@fedoraproject.org OK\n' % self.users[uid]['username'])
    #username_email = [(self.users[uid]['username'],
    #    self.users[uid]['email']) for uid in self.good_users]
    username_email.sort()
 
    for username, email in username_email:
        email_file.write('%s: %s\n' % (username, email))
 
    for groupname, group in sorted(self.groups.iteritems()):
        administrators = []
        sponsors = []
        members = []
 
        for uid in group['users']:
            if uid in self.good_users:
                # The user has an @fedoraproject.org alias
                username = self.users[uid]['username']
                members.append(username)
            else:
                # Add their email if they aren't disabled.
                if uid in self.users:
                    members.append(self.users[uid]['email'])
 
        for uid in group['sponsors']:
            if uid in self.good_users:
                # The user has an @fedoraproject.org alias
                username = self.users[uid]['username']
                sponsors.append(username)
                members.append(username)
            else:
                # Add their email if they aren't disabled.
                if uid in self.users:
                    sponsors.append(self.users[uid]['email'])
                    members.append(self.users[uid]['email'])
        for uid in group['administrators']:
            if uid in self.good_users:
                # The user has an @fedoraproject.org alias
                username = self.users[uid]['username']
                administrators.append(username)
                sponsors.append(username)
                members.append(username)
            else:
                # Add their email if they aren't disabled.
                if uid in self.users:
                    administrators.append(self.users[uid]['email'])
                    sponsors.append(self.users[uid]['email'])
                    members.append(self.users[uid]['email'])

        if administrators:
            administrators.sort()
            email_file.write('%s-administrators: %s\n' % (groupname, ','.join(administrators)))
        if sponsors:
            sponsors.sort()
            email_file.write('%s-sponsors: %s\n' % (groupname, ','.join(sponsors)))
        if members:
            members.sort()
            email_file.write('%s-members: %s\n' % (groupname, ','.join(members)))
    email_file.close()
    recipient_file.close()

def update_authconfig(option=None):
    """Enable FAS authentication on system"""
    config = read_config()
    temp = path(tempfile.mkdtemp('', 'fas-', config.get('global', 'temp').strip('"')))

    old = path('/etc/sysconfig/authconfig')
    new = temp.joinpath('authconfig')

    for line in old.lines():
        if line.startswith('USEDB'):
            new.write_text(option, linesep='\n', append=True)
        else:
            new.write_text(line, append=True)

    try:
        move(new, '/etc/sysconfig/authconfig')
    except IOError, e:
        print >> sys.stderr, 'ERROR: Could not write /etc/sysconfig/authconfig: %s' % e
        sys.exit(5)
    authconfig('--updateall')
    #rmtree(temp)

def chown(arg, dir_name, files):
    os.chown(dir_name, arg[0], arg[1])
    for file in files:
        os.chown(os.path.join(dir_name, file), arg[0], arg[1])

def drop_privs(pw):
    # initgroups is only in python >= 2.7
    #os.initgroups(pw.pw_name, pw.pw_gid)
    groups = set(os.getgroups())
    groups.add(pw.pw_gid)

    os.setgroups(list(groups))
    os.setegid(pw.pw_gid)
    os.seteuid(pw.pw_uid)
