import logging
from vc3infoservice.core import InfoEntity

class User(InfoEntity):
    '''
    Represents a VC3 instance user account.
    As policy, name, email, and organization must be set.  
    
    '''
    infoattributes = ['name',
                     'state',
                     'acl',
                     'first',
                     'last',
                     'email',
                     'organization',
                     'identity_id',
                     'description',
                     'displayname',
                     'url',
                     'docurl'                  
                     ] 
    infokey = 'user'
    validvalues = {}
    intattributes = []
    
    def __init__(self,
                   name,
                   state,
                   acl,
                   first,
                   last,
                   email,
                   organization,
                   identity_id=None,
                   description=None,
                   displayname=None,
                   url=None,
                   docurl=None
                ):
        '''
        Defines a new User object. 
              
        :param str name: The unique VC3 username of this user
        :param str first: User's first name
        :param str last: User's last name
        :param str email: User's email address
        :param str organization: User's institutional affiliation or employer
        :param str description: Long-form description
        :param str displayname: Pretty human-readable name/short description
        :param str url: High-level URL reference for this entity. 
        :param str docurl: Link to how-to/usage documentation for this entity.          
        :return: User:  A valid User object      
        :rtype: User
        
        '''
        self.log = logging.getLogger()
        self.state = state
        self.acl = acl
        self.name = name
        self.first = first
        self.last = last
        self.email = email
        self.organization = organization
        self.identity_id = identity_id
        self.allocations = []
        self.description = description
        self.displayname = displayname
        self.url = url
        self.docurl = docurl
        self.log.debug("Entity created: %s" % self)

