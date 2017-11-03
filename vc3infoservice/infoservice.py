#! /usr/bin/env python
__author__ = "John Hover, Jose Caballero"
__copyright__ = "2017 John Hover"
__credits__ = []
__license__ = "GPL"
__version__ = "0.9.1"
__maintainer__ = "John Hover"
__email__ = "jhover@bnl.gov"
__status__ = "Production"


import cherrypy
import inspect
import logging
import logging.handlers
import os
import platform
import pwd
import random
import json
import string
import socket
import sys
import threading
import time
import traceback

from optparse import OptionParser
from ConfigParser import ConfigParser

from vc3infoservice.core  import InfoEntityExistsException, InfoEntityMissingException
from miracle.acl import Acl

import pluginmanager as pm


class InfoHandler(object):
    '''
    Handles low-level operations and persistence of information 
    from service using back-end plugin.
    
    Inbound arguments of InfoServiceAPI are JSON strings. These are converted to Python 
    primitive objects for persistence plugin calls. 

    inbound entities are expected to be in the form of JSON with entity.name indices, e.g.
        '{ "name" : { "name" : "namevalue", "key1" : "val1" }}' 
    
    returned entities are in the form of unindexed entity JSON dictionaries , e.g. 
        '{ "name" : "namevalue", "key1" : "val1" }'
     
    '''
    def __init__(self, config):
        self.log = logging.getLogger()
        self.log.debug("Initializing Info Handler...")
        self.config = config
        
        # Get persistence plugin
        pluginname = config.get('persistence','plugin')
        psect = "plugin-%s" % pluginname.lower()
        self.log.debug("Creating persistence plugin...")
        self.persist = pm.getplugin(parent=self, 
                                    paths=['vc3infoservice', 'plugins', 'persist'], 
                                    name=pluginname, 
                                    config=self.config, 
                                    section=psect)
        self.log.debug("Done initializing InfoHandler")

################################################################################
#                     Entity-oriented methods
################################################################################

    def storeentity(self, key, entityname, edoc):
        '''
        Stores contents of JSON doc string by entity level. If entity already exists, does not 
        do so. 
        
        Entity doc:  
         {"username": {"last": "Last", 
                        "name": "username", 
                        "acl": null,
                       }
                   }
        '''
        self.logrequest()
        self.log.debug("input JSON doc to merge is %s" % edoc)
        entitydict = json.loads(edoc)
        self.persist.lock.acquire()
        try:
            currentdoc = self.persist.getdocument(key)
            try:
                existingentity = currentdoc[entityname]
                cherrypy.response.status = 405
                return "Attempt to create (POST) already-existing Entity. Name: %s. " % entityname
            except KeyError:
                self.log.debug("No existing entity %s. As expected..." % entityname)
                pass
            
            self.log.debug("Merging entity with existing document.")
            newdoc = self.merge( entitydict, currentdoc)
            self.persist.storedocument(key, newdoc)
            self.log.debug("Successfully stored entity.")            
        finally:
            self.persist.lock.release()        

    def mergeentity(self, key, entityname, edoc):
        '''
        merges contents of (update-only) JSON doc string by entity level. 
        Within entity, uses merge that replaces attributes with new values.
        '''
        self.log.debug("input entity doc to merge is %s" % edoc)       
        # e.g. {"SPT": {"allocations": ["lincolnb.uchicago-midway"]}}
        self.log.debug("input JSON doc to merge is type %s" % type(edoc))
        entitydict = json.loads(edoc)
        self.persist.lock.acquire()
        try:
            currentdoc = self.persist.getdocument(key)
            existingentity = currentdoc[entityname]
            newentity = entitydict[entityname]
            #self.log.debug("Existing entity: %s" % existingentity)
            #self.log.debug("New entity:" % newentity)
            #self.log.debug("Merging newentity with existing entity.")
            self.entitymerge(newentity, existingentity)
            #self.log.debug("Resulting existing: %s" % existingentity)
            self.persist.storedocument(key, currentdoc)
            self.log.debug("Successfully stored entity.")            
        except KeyError:
            cherrypy.response.status = 405
            return "Attempt to update (PUT) non-existent Entity. Name: %s. " % entityname
        finally:
            self.persist.lock.release()        

    def entitymerge(self, src, dest):
            ''' 
            Merges bare src entity into dest entity, unconditionally replacing *attribute* 
            values at entity-attribute level. Intended to be used in-place, so dest is not returned. 
            
            { u'allocations': [u'lincolnb.uchicago-midway']}
             + 
            { u'allocations': [], 
              u'name': u'SPT', 
              u'blueprints': []  }
             =
             {u'allocations': [u'lincolnb.uchicago-midway'],
             u'name': u'SPT', 
             u'blueprints': []}
             
            '''
            self.log.debug("Handling merging %s into %s " % (src, dest))
            for attributename in src.keys():
                dest[attributename] = src[attributename]

    def getentity(self, key, entityname):
        '''
        Gets JSON representation of entity.
        
        { 'name' : <entityname>',
          'key1'  : '<val1>'
        }        
        '''
        self.logrequest()
        currentdoc = self.persist.getdocument(key)
        self.log.debug("Current doc for %s is %s" % (key, currentdoc))
        try:
            ed = currentdoc[entityname]
            je = json.dumps(ed)
            self.log.debug("JSON entity is %s" % str(je))
            return je
        except KeyError:
            cherrypy.response.status = 405
            return "Attempt to GET non-existent Entity. Name: %s. " % entityname
            #raise InfoEntityMissingException("Attempt to update or get a non-existent Entity.")


    def deleteentity(self, key, entityname):
        '''
        deletes relevant entity, if it exists. 
        '''
        self.persist.lock.acquire()
        try:
            doc = self.persist.getdocument(key)
            self.log.debug("Deleting entity %s in key %s" % (entityname, key))
            doc.pop(entityname)
            self.persist.storedocument(key, doc)
            self.log.debug("Successfully stored.")            
        except KeyError:
            cherrypy.response.status = 405
            return "Entity %s not found, so can't delete it." % entityname
        finally:
            self.persist.lock.release()   

################################################################################
#                     Category document-oriented methods
################################################################################
  
    def storedocument(self, key, doc):
        '''
        Overwrites existing document with new.
        '''
        self.logrequest()
        self.log.debug("Storing document for key %s" % key)
        pd = json.loads(doc)
        self.persist.lock.acquire()
        try:
            self.persist.storedocument(key, pd)
        finally:
            self.persist.lock.release()
    
    def mergedocument(self, key, doc):
        self.log.debug("Merging document for key %s" % key)
        self.persist.lock.acquire()
        try:
            dcurrent = self.persist.getdocument(key)
            #pd = json.loads(doc)
            
            self.persist.storedocument(key, pd)
        finally:
            self.persist.lock.release()

        self.persist.lock.acquire()
        try:
            dcurrent = self.persist.getdocument(key)
            self.log.debug("current retrieved doc is type %s" % type(dcurrent))
            md = json.loads(doc)
            self.log.debug("doc to merge is type %s" % type(md))
            newdoc = self.merge( md, dcurrent)
            self.log.debug("Merging document for key %s" % key)
            self.persist.storedocument(key, newdoc)
        finally:
            self.persist.lock.release()      

    def deletedocument(self, key):
        self.log.debug("Deleting document for key %s" % key)
        #pd = json.loads(doc)
        self.persist.lock.acquire()
        emptydict = {}
        try:
            self.persist.storedocument(key, emptydict)
        finally:
            self.persist.lock.release()

    def getdocument(self, key):
        '''
        Gets JSON representation of document. 
        '''
        self.logrequest()
        pd = self.persist.getdocument(key)
        jd = json.dumps(pd)
        self.log.debug("d is type %s" % type(jd))
        return jd

################################################################################
#                     Utility methods
################################################################################

    def logrequest(self):
        
        peercert = cherrypy.serving.request.rfile.rfile._sock.get_peer_certificate()
        self.log.info("Peercert is %s " % peercert)
        if peercert is not None:
            subj = peercert.get_subject()
            ver = peercert.get_version()
            issuer = peercert.get_issuer()
            #self.log.debug("dir(subj) %s" % dir(subj))
            self.log.info("Cert info: subject=%s ssl_version=%s issuer=%s" % (subj.commonName, ver, issuer.commonName))
        else:
            self.log.info("Peer cert is still none!")          
        
        return

    '''
        r = cherrypy.request
        self.log.info("###########################################################################################")
        self.log.info("cherrpy.request = %s" % str(r))
        for (k, v) in inspect.getmembers(r):
            if not k.startswith('__'):
                if inspect.ismethod(v):
                    self.log.info("    %s()" % k )
                else:
                    self.log.info("    %s = %s" % (k, v))

        s = cherrypy.serving
        self.log.info("###########################################################################################")
        self.log.info("cherrypy.serving = %s" % str(s))
        for (k, v) in inspect.getmembers(s):
            if not k.startswith('__'):
                if inspect.ismethod(v):
                    self.log.info("    %s()" % k )
                else:
                    self.log.info("    %s = %s" % (k, v))        

        
        sr = cherrypy.serving.request
        self.log.info("###########################################################################################")
        self.log.info("cherrypy.serving.request = %s" % str(sr))
        for (k, v) in inspect.getmembers(sr):
            if not k.startswith('__'):
                if inspect.ismethod(v):
                    self.log.info("    %s()" % k )
                else:
                    self.log.info("    %s = %s" % (k, v))            
        
        
        rf = cherrypy.serving.request.rfile
        self.log.info("###########################################################################################")
        self.log.info("cherrypy.serving.request.rfile = %s" % str(rf))
        for (k, v) in inspect.getmembers(rf):
            if not k.startswith('__'):
                if inspect.ismethod(v):
                    self.log.info("    %s()" % k )
                else:
                    self.log.info("    %s = %s" % (k, v))         

        rfrf = cherrypy.serving.request.rfile.rfile
        self.log.info("###########################################################################################")
        self.log.info("cherrypy.serving.request.rfile.rfile = %s" % str(rfrf))
        for (k, v) in inspect.getmembers(rfrf):
            if not k.startswith('__'):
                if inspect.ismethod(v):
                    self.log.info("    %s()" % k )
                else:
                    self.log.info("    %s = %s" % (k, v)) 

        rfrfs = cherrypy.serving.request.rfile.rfile._sock
        self.log.info("###########################################################################################")
        self.log.info("cherrypy.serving.request.rfile.rfile._sock = %s" % str(rfrfs))
        for (k, v) in inspect.getmembers(rfrfs):
            if not k.startswith('__'):
                if inspect.ismethod(v):
                    self.log.info("    %s()" % k )
                else:
                    self.log.info("    %s = %s" % (k, v))

       
        #while True:      
        #    try:
        #        cherrypy.serving.request.rfile.rfile._sock.do_handshake()
        #        self.log.info("do_handshake() didn't cause exception...")
        #    except Exception, e:
        #        self.log.error("Exception recieved %s" % e)
        
        #cherrypy.serving.request.rfile.rfile._sock.do_handshake()       
    '''              
        
        

#    def _getpythondocument(self, key):
#        '''
#        Gets Python object. 
#        '''
#        d = self.persist.getdocument(key)
#        self.log.debug("d is type %s with value %s" % (type(d), d))
#        return d
    
#    def _storepythondocument(self, key, pd):
#        self.log.debug("Storing document for key %s" % key)
#        self.persist.storedocument(key, pd)
    
    
#    def deletesubtree(self, path):
#        lst = path.split('.')
#        try:
#            self.persist.deletesubtree(lst)
#        except IndexError:
#            raise Exception('path should have more than one key')

    def merge(self, src, dest):
            ''' 
            Merges python primitive object src into dest and returns merged result.
            Lists are appended.
            Dictionaries are merged. 
            Primitive values are overwritten. 
            NOTE: tuples and arbitrary objects are not handled as it is totally ambiguous what should happen
            https://stackoverflow.com/questions/7204805/dictionaries-of-dictionaries-merge/15836901
            '''
            key = None
            # ## debug output
            # sys.stderr.write("DEBUG: %s to %s\n" %(b,a))
            self.log.debug("Handling merging %s into %s " % (src, dest))
            try:
                if dest is None or isinstance(dest, str) or isinstance(dest, unicode) or isinstance(dest, int) \
                             or isinstance(dest, long) or isinstance(dest, float):
                    # border case for first run or if a is a primitive
                    dest = src
                elif isinstance(dest, list):
                    # lists can be only appended
                    if isinstance(src, list):
                        # merge lists
                        for item in src:
                            if item not in dest:
                                dest.append(item)
                        #dest.extend(src)
                    else:
                        self.log.error("Refusing to add non-list %s to list %s" % (src, dest))
                        # append to list
                        #dest.append(src)
                elif isinstance(dest, dict):
                    # dicts must be merged
                    if isinstance(src, dict):
                        for key in src:
                            if key in dest:
                                dest[key] = self.merge(src[key], dest[key])
                            else:
                                dest[key] = src[key]
                    elif src is None:
                        dest = None
                    else:
                        self.log.warning("Cannot merge non-dict %s into dict %s" % (src, dest))
                else:
                    raise Exception('NOT IMPLEMENTED "%s" into "%s"' % (src, dest))
            except TypeError, e:
                raise Exception('TypeError "%s" in key "%s" when merging "%s" into "%s"' % (e, key, src, dest))
            return dest


##################################################################################
#                             Infrastructural methods 
##################################################################################
    
    def getpairing(self, key, pairingcode):
        '''
        Pull pairing document, check each entry to see if <entry>.pairingcode = pairingcode.
        If so, and cert and key are not none, prepare to return them, delete entry, return Pairing
        '''
        self.logrequest()
        failmsg="Invalid pairing code or not satisfied yet. Try in 30 seconds."
        prd = None
        pd = self._getpythondocument(key)
        self.log.debug("Received dict: %s" % pd)
        try:        
            self.log.debug("Entries are %s" % pd[key] )
            for p in pd[key].keys():
                self.log.debug("Checking entry %s for pairingcode..." % p)
                if pd[key][p]['pairingcode'] == pairingcode:
                    self.log.debug("Found matching entry %s value %s" % (p, pd[key][p]))
                    if pd[key][p]['cert'] is not None:
                        prd = json.dumps(pd[key][p])
                        try:
                            self.log.debug("Attempting to delete entry %s from pairing." % p)
                            pd[key].pop(p, None)
                            self.log.debug("Deleted entry %s from pairing. Re-storing.." % p)
                        except KeyError:
                            self.log.warning("Failed to delete entry %s from pairing." % p)
                        self._storepythondocument(key, pd)
                    else:
                        self.log.info("Certificate for requested pairing not generated yet.")
            self.log.debug("Returning pairing entry JSON %s" % prd)
            if prd is None:
                cherrypy.response.headers["Status"] = "404"
                return failmsg
            return prd
        except KeyError:
            cherrypy.response.headers["Status"] = "404"
            return failmsg

    def getCAChain(self):
        '''
        
        '''
        pass
   

class InfoRoot(object):

    @cherrypy.expose
    def index(self):
        return "Nothing to see. Go to /info"    

    @cherrypy.expose
    def generate(self, length=8):
        return ''.join(random.sample(string.hexdigits, int(length)))

class InfoServiceAPI(object):
    ''' 
        Data at this level is assumed to be  JSON text/plain. 
    
    '''
    exposed = True 
    
    def __init__(self, config):
        self.log = logging.getLogger()
        self.log.debug("Initting InfoServiceAPI...")
        self.infohandler = InfoHandler(config)
        self.log.debug("InfoServiceAPI init done." )
    
    def GET(self, key, pairingcode=None, entityname=None):
        if pairingcode is None and entityname is None:
            d = self.infohandler.getdocument(key) 
            self.log.debug("Document retrieved for key %s " % key)
            return d
        elif pairingcode is None:
            e = self.infohandler.getentity(key, entityname) 
            self.log.debug("Entity retrieved for key %s and name %s" % (key,entityname))
            return e
        else:
            self.log.debug("Handling pairing retrieval")
            d = self.infohandler.getpairing(key, pairingcode)
            self.log.debug("Pairing retrieved for code %s with val %s" % (pairingcode,d))
            return d

    @cherrypy.tools.accept(media='text/plain')
    def PUT(self, key, entityname=None, data=None):
        rtext = "Something went wrong..."
        if entityname is None:
            self.log.debug("Storing document %s" % data)
            self.infohandler.mergedocument(key, data)
            self.log.debug("Document stored for key %s" % key)
            rtext= "Document stored for key %s\n" % key
        else:
            self.log.debug("Storing key %s entityname %s " % (key, entityname))
            self.infohandler.mergeentity(key, entityname, data)
            rtext= "Entity %s stored in key %s\n" % (entityname, key )
        return rtext

        
    def POST(self, key, entityname=None, data=None):
        rtext = "Something went wrong..."
        if entityname is None:
            self.log.debug("Storing document %s" % data)
            self.infohandler.storedocument(key, data)
            self.log.debug("Document stored for key %s" % key)
            rtext= "Document stored for key %s\n" % key
        else:
            self.log.debug("Storing key %s entityname %s " % (key, entityname))
            self.infohandler.storeentity(key, entityname, data)
            rtext= "Entity %s stored in key %s\n" % (entityname, key )
        return rtext
        
    def DELETE(self, key, entityname ):
        '''
        Deletes specified entity from <key> document. 
        '''
        self.infohandler.deleteentity(key, entityname)
        rtext= "Entity %s deleted in key %s\n" % (entityname, key )
        return rtext


    def stripquotes(self,s):
        rs = s.replace("'","")
        return rs


class InfoService(object):
    
    def __init__(self, config):
        self.log = logging.getLogger()
        self.log.debug('InfoService class init...')
        self.config = config
        self.certfile = os.path.expanduser(config.get('netcomm','certfile'))
        self.keyfile = os.path.expanduser(config.get('netcomm', 'keyfile'))
        self.chainfile = os.path.expanduser(config.get('netcomm','chainfile'))
        self.httpport = int(config.get('netcomm','httpport'))
        self.httpsport = int(config.get('netcomm','httpsport'))
        self.sslmodule = config.get('netcomm','sslmodule')
        
        self.log.debug("certfile=%s" % self.certfile)
        self.log.debug("keyfile=%s" % self.keyfile)
        self.log.debug("chainfile=%s" % self.chainfile)
        
        self.log.debug('InfoService class done.')
        
    def run(self):
        self.log.debug('Infoservice running...')
          
        cherrypy.tree.mount(InfoRoot())
        cherrypy.tree.mount(InfoServiceAPI(self.config),'/info',
                                {'/':
        {'request.dispatch': cherrypy.dispatch.MethodDispatcher()}
    })
        #cherrypy.tree.mount(InfoServiceAPI(self.config))
        
        
        cherrypy.server.unsubscribe()
    
        server1 = cherrypy._cpserver.Server()
        server1.socket_port=self.httpsport
        server1._socket_host='0.0.0.0'
        server1.thread_pool=30
        server1.ssl_module = self.sslmodule
        server1.ssl_certificate = self.certfile
        server1.ssl_private_key = self.keyfile
        server1.ssl_certificate_chain = self.chainfile
        server1.subscribe()
    
        #server2 = cherrypy._cpserver.Server()
        #server2.socket_port=self.httpport
        #server2._socket_host="0.0.0.0"
        #server2.thread_pool=30
        #server2.subscribe()
    
        cherrypy.engine.start()
        cherrypy.engine.block()   
    

class InfoServiceCLI(object):
    """class to handle the command line invocation of service. 
       parse the input options,
       setup everything, and run InfoService class
    """
    def __init__(self):
        self.options = None 
        self.args = None
        self.log = None
        self.config = None

        self.__presetups()
        self.__parseopts()
        self.__setuplogging()
        self.__platforminfo()
        self.__checkroot()
        self.__createconfig()

    def __presetups(self):
        '''
        we put here some preliminary steps that 
        for one reason or another 
        must be done before anything else
        '''

    
    def __parseopts(self):
        parser = OptionParser(usage='''%prog [OPTIONS]
vc3-infoservice is a information store for VC3

This program is licenced under the GPL, as set out in LICENSE file.

Author(s):
John Hover <jhover@bnl.gov>
''', version="%prog $Id: infoservice.py 1-13-17 23:58:06Z jhover $" )

        parser.add_option("-d", "--debug", 
                          dest="logLevel", 
                          default=logging.WARNING,
                          action="store_const", 
                          const=logging.DEBUG, 
                          help="Set logging level to DEBUG [default WARNING]")
        parser.add_option("-v", "--info", 
                          dest="logLevel", 
                          default=logging.WARNING,
                          action="store_const", 
                          const=logging.INFO, 
                          help="Set logging level to INFO [default WARNING]")
        parser.add_option("--console", 
                          dest="console", 
                          default=False,
                          action="store_true", 
                          help="Forces debug and info messages to be sent to the console")
        parser.add_option("--quiet", dest="logLevel", 
                          default=logging.WARNING,
                          action="store_const", 
                          const=logging.WARNING, 
                          help="Set logging level to WARNING [default]")
        parser.add_option("--maxlogsize", dest="maxlogsize",
                          default=4096,
                          action="store",
                          type="int",
                          help="Max log size, in MB.")
        parser.add_option("--logrotations", dest="logrotations",
                          default=2,
                          action="store",
                          type="int",
                          help="Number of log backups to keep.")

        default_conf = "/etc/vc3/vc3-infoservice.conf"
        default_conf = ','.join([default_conf, os.path.expanduser('~/git/vc3-infoservice/etc/vc3-infoservice.conf')])
        if 'VC3_SERVICES_HOME' in os.environ:
            # if running inside the builder...
            default_conf = ','.join([default_conf, os.path.expanduser('~/vc3-services/etc/vc3-infoservice.conf'), os.path.expanduser('~/vc3-services/etc/vc3-infoservice-local.conf')])

        parser.add_option("--conf", dest="confFiles", 
                          default=default_conf,
                          action="store", 
                          metavar="FILE1[,FILE2,FILE3]", 
                          help="Load configuration from FILEs (comma separated list)")

        parser.add_option("--log", dest="logfile", 
                          default="stdout", 
                          metavar="LOGFILE", 
                          action="store", 
                          help="Send logging output to LOGFILE or SYSLOG or stdout [default <syslog>]")
        parser.add_option("--runas", dest="runAs", 
                          #
                          # By default
                          #
                          default=pwd.getpwuid(os.getuid())[0],
                          action="store", 
                          metavar="USERNAME", 
                          help="If run as root, drop privileges to USER")
        (self.options, self.args) = parser.parse_args()

        self.options.confFiles = self.options.confFiles.split(',')

    def __setuplogging(self):
        """ 
        Setup logging 
        """
        self.log = logging.getLogger()
        if self.options.logfile == "stdout":
            logStream = logging.StreamHandler()
        else:
            lf = os.path.expanduser(self.options.logfile)
            logdir = os.path.dirname(lf)
            if not os.path.exists(logdir):
                os.makedirs(logdir)
            runuid = pwd.getpwnam(self.options.runAs).pw_uid
            rungid = pwd.getpwnam(self.options.runAs).pw_gid                  
            os.chown(logdir, runuid, rungid)
            #logStream = logging.FileHandler(filename=lf)
            logStream = logging.handlers.RotatingFileHandler(filename=lf, maxBytes=1024 * 1024 * self.options.maxlogsize, backupCount=self.options.logrotations)

        # Check python version 
        major, minor, release, st, num = sys.version_info
        if major == 2 and minor == 4:
            FORMAT='%(asctime)s (UTC) [ %(levelname)s ] %(name)s %(filename)s:%(lineno)d : %(message)s'
        else:
            FORMAT='%(asctime)s (UTC) [ %(levelname)s ] %(name)s %(filename)s:%(lineno)d %(funcName)s(): %(message)s'
        formatter = logging.Formatter(FORMAT)
        formatter.converter = time.gmtime  # to convert timestamps to UTC
        logStream.setFormatter(formatter)
        self.log.addHandler(logStream)

        # adding a new Handler for the console, 
        # to be used only for DEBUG and INFO modes. 
        if self.options.logLevel in [logging.DEBUG, logging.INFO]:
            if self.options.console:
                console = logging.StreamHandler(sys.stdout)
                console.setFormatter(formatter)
                console.setLevel(self.options.logLevel)
                self.log.addHandler(console)
        self.log.setLevel(self.options.logLevel)
        self.log.info('Logging initialized at level %s.' % self.options.logLevel)


    def _printenv(self):

        envmsg = ''        
        for k in sorted(os.environ.keys()):
            envmsg += '\n%s=%s' %(k, os.environ[k])
        self.log.debug('Environment : %s' %envmsg)


    def __platforminfo(self):
        '''
        display basic info about the platform, for debugging purposes 
        '''
        self.log.info('platform: uname = %s %s %s %s %s %s' %platform.uname())
        self.log.info('platform: platform = %s' %platform.platform())
        self.log.info('platform: python version = %s' %platform.python_version())
        self._printenv()

    def __checkroot(self): 
        """
        If running as root, drop privileges to --runas' account.
        """
        starting_uid = os.getuid()
        starting_gid = os.getgid()
        starting_uid_name = pwd.getpwuid(starting_uid)[0]

        hostname = socket.gethostname()
        
        if os.getuid() != 0:
            self.log.info("Already running as unprivileged user %s at %s" % (starting_uid_name, hostname))
            
        if os.getuid() == 0:
            try:
                runuid = pwd.getpwnam(self.options.runAs).pw_uid
                rungid = pwd.getpwnam(self.options.runAs).pw_gid
                os.chown(self.options.logfile, runuid, rungid)
                
                os.setgid(rungid)
                os.setuid(runuid)
                os.seteuid(runuid)
                os.setegid(rungid)

                self._changehome()
                self._changewd()

                self.log.info("Now running as user %d:%d at %s..." % (runuid, rungid, hostname))
                self._printenv()

            
            except KeyError, e:
                self.log.error('No such user %s, unable run properly. Error: %s' % (self.options.runAs, e))
                sys.exit(1)
                
            except OSError, e:
                self.log.error('Could not set user or group id to %s:%s. Error: %s' % (runuid, rungid, e))
                sys.exit(1)

    def _changehome(self):
        '''
        Set environment HOME to user HOME.
        '''
        runAs_home = pwd.getpwnam(self.options.runAs).pw_dir 
        os.environ['HOME'] = runAs_home
        self.log.debug('Setting up environment variable HOME to %s' %runAs_home)


    def _changewd(self):
        '''
        changing working directory to the HOME directory of the new user,
        '''
        runAs_home = pwd.getpwnam(self.options.runAs).pw_dir
        os.chdir(runAs_home)
        self.log.debug('Switching working directory to %s' %runAs_home)


    def __createconfig(self):
        """Create config, add in options...
        """
        if self.options.confFiles != None:
            try:
                self.log.debug("Conf file list %s" % self.options.confFiles)
                self.config = ConfigParser()
                rfs = self.config.read(self.options.confFiles)
                self.log.debug("Read config file(s) %s" % rfs)
            except Exception, e:
                self.log.error('Config failure')
                sys.exit(1)
        
        #self.config.set("global", "configfiles", self.options.confFiles)
           
    def run(self):
        """
        Create Daemon and enter main loop
        """

        try:
            self.log.info('Creating Daemon and entering main loop...')
            infosrv = InfoService(self.config)
            infosrv.run()
            
        except KeyboardInterrupt:
            self.log.info('Caught keyboard interrupt - exitting')
            f.join()
            sys.exit(0)
        except ImportError, errorMsg:
            self.log.error('Failed to import necessary python module: %s' % errorMsg)
            sys.exit(1)
        except:
            self.log.error('''Unexpected exception!''')
            # The following line prints the exception to the logging module
            self.log.error(traceback.format_exc(None))
            print(traceback.format_exc(None))
            sys.exit(1)          

if __name__ == '__main__':
    iscli = InfoServiceCLI()
    iscli.run()

