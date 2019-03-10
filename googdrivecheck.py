from __future__ import annotations
from pprint import pprint as pp
from typing import Dict, List, NoReturn, Optional
import csv
import pickle

from pydrive.auth import GoogleAuth
from pydrive.drive import GoogleDrive, GoogleDriveFile

def lazy_property_folder_metadata(fn):
    """Decorator for lazily fetching certain file metadata
        For this program probably unnecessary, but it provides some nice protections
    """
    @property
    def _lazy_property(self: Folder):
        if not self._seen:
            self._do_lookup_from_drive()
        if self._metadata_lookup_failed:
            print("Metadata lookup unsuccessful. Yield default. File: %s\t, metadata: %s\t, id: %s" %
                  (self._name, fn.__name__, self.id))
        return fn(self)
    return _lazy_property

''' Brief readme Note:
    Logic flow is as follows: 
    1) Main query loop cycles through all the files that API generates
    2) FolderTracker.log_item() parses each item and determines whether to track the file
    3) Logic flow is log_item() -> SafeFile.review_and_maybe_generate_tracked_file ->
        TrackedFile() -> _fetch_metadata(), where the last fetch is done only for shared items
    4) After all files are parsed, the folder tree is post-processed (traversed) by populate_all_paths (goes up the tree)
        and by traverse_all_children (goes down the tree), if folder info is being printed
    5) Print output to csv / screen
    
    To change files that are tracked, change review_and_maybe_track -> TrackedFile -> _fetch_sharing_metadata
    To change files the API returns, modify the query functions called by main()
'''
# Todo
intense_debug = False
debug = False
run_short_debug = False
should_write_output = True

# Todo: add these to yaml config
# Drive defines "My Drive" as root, but backed up computers are not captured.
my_user_name = "Josh Rozner"
rootdirs = ["My Drive", "My MacBook Air"]
orphan_prefix = "0_orphan"
name_for_non_seeable_folders = "no_name"
tester_id = "0B4aSdoErkE3vRkUwR3ZPaWlxN3c"
max_results_api_setting = 1000
max_metadata_fetch_try_count = 5          # Generally fetch never fails
log_file_if_size_greater_than_limit = 1e8 # (100 MB)

# Util functions
def print_file_note(description_string, file):
    print("file_note: " + description_string +
          ("\n title: %s\t id:%s" % (SafeFile.safe_get(file, 'name'), SafeFile.safe_get(file, 'id'))))
# This function is a little hacky because it's for debugging. We modify File inplace.
def print_set(set_name, file_set: List):
    print("** Printing set: %s" % set_name)
    for file in file_set:
        parent_folder_id = SafeFile.get_parent_id(file)
        parent_folder = all_folders.static_folder_lookup(parent_folder_id, none_is_okay=True)
        file['fullpath'] = SafeFile.get_full_path(file, parent_folder)

    file_set.sort(key=lambda x: x['fullpath'])
    pp([x['fullpath'] for x in file_set])

class FileProperties:
    """Simple class to initialize a dictionary of the properties we will track
        Todo: this should return a copy to avoid problems (versus requiring user to copy)
        Todo: This should be made immutable so that only these properties are writeable (and so that they are all written)

        To add fields: 1) Add to default_dict, 2) Add method in SafeFile to access,
        3) Populate in either review_and_maybe_track or in _fetch_metadata()
    """
    default_dict : Dict[str,bool] = {
        # These are set in SafeFile.review_and_maybe_track()
        "shared" : False,               # Whether file is shard
        "spaces_photo" : False,         # Whether spaces contains "photos"
        "spaces_app" : False,           # Whether spaces has app space
        "trashed" : False,              # Whether trashed
        "multi_owners" : False,         # Whether file has multiple owners (I've never seen this)
        "non_auth_user_file" : False,   # Whether file is owned by another user (i.e. not the running user)
        "is_orphan" : False,            # Whether file is not in one of the specified rootdirs
        "has_multiple_parents" : False, # Whether file has multiple parent directories
        "file_size" : 0,

        # These are set in TrackedFile._fetch_metadata() (populated only if shared = True)
        "has_more_than_one_permission" : False, # Whether file has more than one access permission. Equivalent to shared.
        "has_non_user_or_anyone_permission" : False,      # Whether file has a permission that is not use or anyone
                                                          # As of this writing that is domain or group
        "has_link_sharing" : False,                       # Equivalent to having an 'anyone' permission
        "users_domains_groups_with_access" : []           # Specific groups, users, domains with access
    }

class SafeFile:
    """ Use this class to access fields in GoogleDriveFile, in case API ever changes
    Any special drive-like strings that are API dependent should be written here so that this
    is the only class that requires changing upon a library / API change.
    """
    # Maps the field we want onto the underlying field in the Drive API. Not everything
    # Is written into this. Some fields are fleshed out below in this class
    # Any field accessed multiple times should probably be included in this property_mapping
    property_mapping = {
        'name' : 'title',
        'id' : 'id',
        'mimeType' : 'mimeType',
        'owners' : 'owners',
        'ownerNames' : 'ownerNames',
        'url' : 'alternateLink',
        'permissions' : 'permissions',
        'shared' : 'shared',

        # Special properties (not just simple lookups)
        '_safe_parents': 'parents',
        '_spaces': 'spaces',
        '_file_size' : 'fileSize'# Not always populated (e.g. unpopulated for google documents)

        # Special properties that are not fetched with safe_get()
        # labels        # Variety of misc. things. We care about 'trashed'
    }

    @classmethod
    def safe_get(cls, file: GoogleDriveFile, item: str, issue_warning_if_not_present=True):
        """ Safely fetches a given attribute """
        internal_name_for_attr = SafeFile.property_mapping.get(item, None)
        if internal_name_for_attr is None:
            raise Exception("Invalid requested attr in SafeFile: %s" % item)
        #todo: why is file.get(internal_name_for_attr) not working in some cases?
        try:
            attr_value = file[internal_name_for_attr]
        except KeyError:
            if issue_warning_if_not_present:
                print("File %s does not have attr: %s" % (file['title'], internal_name_for_attr))
                pp(file)
            attr_value = None
        return attr_value
    @classmethod
    def get_parent_id(cls, file: GoogleDriveFile) -> Optional[str]:
        """ Get the first parent's ID"""
        # Todo: implement handling of multiple parents (but note that we do print an error and also print
        # At the end of output
        parent_array = SafeFile.safe_get(file, "_safe_parents")
        if len(parent_array) == 0:
            return None
        if(len(parent_array)) > 1:
            print("** more than one parent")
        return parent_array[0]['id']
    @classmethod
    def is_folder(cls, file: GoogleDriveFile) -> bool:
        return SafeFile.safe_get(file, 'mimeType') == "application/vnd.google-apps.folder"
    @classmethod
    def is_root_folder(cls, file:GoogleDriveFile) -> bool:
        return SafeFile.safe_get(file, 'name') in rootdirs and \
               len(SafeFile.safe_get(file, '_safe_parents')) == 0
    @classmethod
    def get_full_path(cls, file:GoogleDriveFile, parent_folder: 'Folder') -> str:
        file_name = SafeFile.safe_get(file, 'name')
        if parent_folder is None:
            return orphan_prefix + "/" + file_name

        parent_folder_path = parent_folder.full_path
        return parent_folder_path + "/" + file_name
    @classmethod
    def get_all_owners(cls, file:GoogleDriveFile) -> List[str]:
        owners = SafeFile.safe_get(file, 'owners')
        return list(x['displayName'] for x in owners)
    @classmethod
    def has_link_sharing(cls, file:GoogleDriveFile) -> bool:
        if "anyone" in SafeFile.non_user_permissions_type_list(file):
            return True
        return False
    @classmethod
    def non_user_permissions_type_list(cls, file:GoogleDriveFile) -> List[str]:
        permissions = SafeFile.safe_get(file, 'permissions')
        return list(perm['type']
                    for perm in permissions if perm['type'] not in ["user"])
    @classmethod
    # Todo: verify domain works
    def special_permissions_list(cls, file:GoogleDriveFile) -> List[List[str]]:
        permissions = SafeFile.safe_get(file, 'permissions')
        return list([perm['type'],perm.get('emailAddress')]
                    for perm in permissions if perm['type'] not in ["user", "anyone"])
    @classmethod
    def users_groups_domains_with_access(cls, file:GoogleDriveFile) -> List[str]:
        permissions = SafeFile.safe_get(file, 'permissions')
        return_list = []
        for perm in permissions:
            if perm['type'] == "anyone": continue

            if perm['type'] in ["user", "group"]: return_list.append(perm['emailAddress'])
            elif perm['type'] == "domain": return_list.append(perm['domain'])
            else: raise Exception("Unhandled permission type: %s" % perm['type'])
        return return_list

    @classmethod
    def file_size(cls, file:GoogleDriveFile) -> int:
        # FileSize is not populated for google docs
        file_size = SafeFile.safe_get(file, '_file_size', issue_warning_if_not_present=False)
        if file_size is None:
            file_size = 0
        return file_size

    @classmethod
    def review_and_maybe_generate_tracked_file(cls, file: GoogleDriveFile, parent: 'Folder') -> Optional['TrackedFile']:
        """ Determine whether a given file should be tracked. If yes return TrackedFile"""
        properties_dict = FileProperties.default_dict.copy()    #This was a big mistake

        if SafeFile.safe_get(file, 'shared'):
            properties_dict['shared'] = True

        if "photos" in SafeFile.safe_get(file, '_spaces'):
            properties_dict['spaces_photo'] = True
        elif "spaces_app" in SafeFile.safe_get(file, '_spaces'):
            properties_dict['spaces_app'] = True
            print_file_note("App space", file)

        if file['labels']['trashed']:
            properties_dict['trashed'] = True
            print_file_note("file is trashed", file)
        if len(file['owners']) > 1:
            properties_dict['multi_owners'] = True
            print_file_note("file has multi owners", file)
        if not my_user_name in file['ownerNames']:
            properties_dict['non_auth_user_file'] = True
        if len(file['owners']) != len(file['ownerNames']):
            print_file_note("owners and ownerNames are different lengths", file)
        if parent is None and not SafeFile.is_root_folder(file):
            properties_dict['is_orphan'] = True
        if len(SafeFile.safe_get(file, "_safe_parents")) > 1:
            properties_dict['has_multiple_parents'] = True
            print_file_note("has multiple parents", file)

        file_size = int(SafeFile.file_size(file))
        if file_size > log_file_if_size_greater_than_limit:
            properties_dict['file_size'] = file_size

        if True in properties_dict.values():
            return TrackedFile(file, properties_dict, parent)
        return None


class TrackedFile:
    """A file that has a property we care about. Files without interesting properties are not tracked (save space)
        After being initialized, everything can be safely accessed. Generally set once and then read upon output
        Fetches sharing metadata only if needed
    """
    def __init__(self, file: GoogleDriveFile, properties_dictionary: dict, parent_folder: 'Folder'):
        self.file = file
        self.props = properties_dictionary
        self.parent_folder = parent_folder

        # Metadata fetch is expensive, so
        # Only fetch sharing for files owned by us (if not owned by us, of course it's shared!) and that are shared
        if not properties_dictionary['non_auth_user_file'] and properties_dictionary['shared']:
            self._fetch_sharing_metadata()

    def __repr__(self):
        return SafeFile.safe_get(self.file, 'name') + "\n" + self.props.__repr__()

    def tracked_file_csv_info(self):
        # Copy over the props we already have, then add in other fields to write.
        # Todo: these fields must match those in the csv writing in main()
        output_dict = self.props.copy()
        output_dict['name'] = SafeFile.safe_get(self.file,'name')
        output_dict['id'] = SafeFile.safe_get(self.file, 'id')
        output_dict['url'] = SafeFile.safe_get(self.file, 'url')
        output_dict['fullpath'] = SafeFile.get_full_path(self.file, self.parent_folder)
        output_dict['all_owners'] = SafeFile.get_all_owners(self.file)
        output_dict['is_folder'] = SafeFile.is_folder(self.file)
        return output_dict

    # Internal method called only for files that are not owned by us and that are shared.
    def _fetch_sharing_metadata(self):
        file = self.file
        is_shared = self.props['shared']

        # Some magic in case fetching fails
        fetch_success = False
        fetch_try_count = 0
        while not fetch_success and fetch_try_count < max_metadata_fetch_try_count:
            try:
                file.FetchMetadata(fetch_all=True)
                fetch_success = True
                if fetch_try_count > 0:
                    print("fetch success after %d tries" % fetch_try_count)
                break
            except Exception as e:
                if fetch_try_count == 0:
                    print("error fetching metadata for title: %s\t id: %s" %
                          (SafeFile.safe_get(file, 'name'), SafeFile.safe_get(file, 'id')))
                    print(str(e))
                fetch_try_count += 1

        # Fail early if all fetches failed
        if not fetch_success:
            print("fetches failed %d times. Abandoning" % fetch_try_count)
            return

        has_more_than_one_permission = False   # This is not particularly useful
        has_non_user_or_anyone_permission = False        # This in general will match link_sharing, except in rare cases
        has_link_sharing = False

        if len(SafeFile.safe_get(file, 'permissions')) > 1:
            self.props['has_more_than_one_permission'] = True

        special_permissions_info = SafeFile.special_permissions_list(file)
        if len(special_permissions_info) > 0:
            print_file_note("non user-anyone permission type", file)
            pp(special_permissions_info)
            self.props['has_non_user_or_anyone_permission'] = True

        if SafeFile.has_link_sharing(file):
            self.props['has_link_sharing'] = True

        self.props['users_groups_domains_with_access'] = SafeFile.users_groups_domains_with_access(file)

        # Some verifications based on our expectations of how sharing works.
        # These can be removed; they have been verified in my experience
        if has_non_user_or_anyone_permission:
            assert(has_more_than_one_permission and is_shared)
        # Check that it's shared if any of the three conditions are met
        if has_more_than_one_permission or has_non_user_or_anyone_permission or has_link_sharing:
            assert is_shared
        # If link sharing, then it has multiple permissions and one is non sharing
        if has_link_sharing:
            assert(has_more_than_one_permission and has_non_user_or_anyone_permission and is_shared)

# Represents an individual folder (a file type). Basically behaves like a tree node
# with some added special features so that we can lazily populate data as the
# API returns. We don't require any guarantees on the order of returned items.
class Folder:
    def __repr__(self):
        return " ".join("{}={!r}".format(k, v) for k, v in self.__dict__.items())

    def __init__(self, file_id: str):
        self.id = file_id

        # These fields are populated during tree traversal.
        # Avoid accessing until tree traversal is complete
        self.num_direct_children = 0
        self.size_of_direct_children = 0
        self.child_folders: List[Folder] = []

        # Whether file has been explicitly processed (i.e. returned from the API vs just seen as a parent node)
        self._seen = False      # Set to true when parsed; Indicates whether this folder has been
                                # Set by populate_fields_from_file
        self._metadata_lookup_failed = False    # If we tried a fetch and failed. We don't keep trying.
                                                # If this is true, self._seen will also be true.

        # Properties (looked up lazily and protected by property method). Default values below.
        # Guarded by self._seen
        self._is_orphan = False
        self._is_root = False
        self._full_path = None      # Generally set during post-processing. Lazily fetched
        self._name = ""             # Set at file lookup. Lazily fetched
        self._parent_folder = None  # Set by file lookup. Lazily fetched
        self._url = ""
        self._owners = []

        # True post processing (last traverse of tree). If these values differ from -1, then have been set
        self._all_children_count = -1         # count of all individual subchildren (through subdirectories to end)
        self._total_size_all_contents = -1    # total size of all the contents of this folder
        self._depth = -1                      # Depth of this node from root or from top level orphan (todo verify)

    # Populates all fields for the folder. Should only be called once per folder. Raises exception if called again.
    # Called either during normal API processing, or after a lazy metadata fetch (by _do_lookup_from_drive)
    def populate_fields_from_file(self, file: GoogleDriveFile, parent_folder: 'Folder'):
        if self._seen:
            raise Exception("Fields have already been populated once")
        if self._metadata_lookup_failed:
            raise Exception("Metadata lookup failed. Invalid call to populate fields")
        self._seen = True

        self._name = SafeFile.safe_get(file, 'name')
        self._parent_folder = parent_folder
        self._url = SafeFile.safe_get(file, 'url')
        self._owners = SafeFile.get_all_owners(file)

        if self._parent_folder is None:
            if SafeFile.is_root_folder(file): self._is_root = True
            else: self._is_orphan = True

    # Do a google drive lookup and fill the normal fields. For folders that weren't seen during normal API handling,
    # Generally only for end metadata lookups (often only for the root folder Google Drive)
    # This was probably an excessive amount of coding for something that is rarely handled.
    # This will be called more for processing upper nodes when starting from a lower node
    # in run_with_recursive_lookup()
    # Used for lazy fetching!
    # todo: logic is duplicated from log_item
    def _do_lookup_from_drive(self):
        if self._seen or self._metadata_lookup_failed:
            return

        file_to_fetch = None
        try:
            # We try to fetch the data for this file
            file_to_fetch = drive.CreateFile({'id': self.id})
            print("fetched metadata for %s" % SafeFile.safe_get(file_to_fetch, 'name'))

            parent_id = SafeFile.get_parent_id(file_to_fetch)
            parent_folder = None
            if parent_id is not None:
                parent_folder = all_folders.get_folder_or_initialize(parent_id)
                parent_folder.num_direct_children += 1
                filesize = SafeFile.file_size(file_to_fetch)
                parent_folder.size_of_direct_children += int(filesize)
                parent_folder.child_folders.append(self)

            self.populate_fields_from_file(file_to_fetch, parent_folder)
            file_to_track = SafeFile.review_and_maybe_generate_tracked_file(file_to_fetch, parent_folder)
            if file_to_track is not None:
                tracked_files[self.id] = file_to_track
        except Exception as e:
            print("error trying to fetch folder %s" % self.id)
            print(str(e))
            pp(file_to_fetch)
            pp(self)
            self._metadata_lookup_failed = True
            self._name = name_for_non_seeable_folders

    # Recursively lookup fullpaths through the folder tree
    @property
    def full_path(self):
        # Quick fail if we've already done this node
        if self._full_path is not None:
            return self._full_path

        # If we never encountered this folder before, then we walk up the folder tree doing lookups
        # In a single function call, this should populate the current folder's parent
        if not self._seen and not self._metadata_lookup_failed:
            self._do_lookup_from_drive()

        if self._metadata_lookup_failed:
            # This file is not "see-able". The folder.name will be name_for_non_seeable_folders
            self._full_path = ".../" + self.name
            return self._full_path

        # Otherwise, file is seen and metadata was looked up. Now we populate the full_path
        if self.parent is not None:
            self._full_path = self.parent.full_path + "/" + self.name
            return self._full_path

        # If we are here, there are no more parents because it is root, orphaned, or error
        if self.is_root:
            self._full_path = self.name
        elif self.is_orphan:
            self._full_path = orphan_prefix + "/" + self.name
        # Else it's a metadata lookup failure
        # We should never get here, since metadata lookup failures already set the fullpath
        else:
            raise Exception("*** ERROR *** no parent (and not root or orphan) for id: %s\n"
                            "This is most likely a code error. We should not reach this point" % self.id)

        return self._full_path

    # Properties that require full metadata and lazily fetch it
    @lazy_property_folder_metadata
    def name(self):
        return self._name
    @lazy_property_folder_metadata
    def parent(self):
        return self._parent_folder
    @lazy_property_folder_metadata
    def is_orphan(self):
        return self._is_orphan
    @lazy_property_folder_metadata
    def is_root(self):
        return self._is_root
    @lazy_property_folder_metadata
    def url(self):
        return self._url
    @lazy_property_folder_metadata
    def owners(self):
        return self._owners

    # Post processing. Both functions are populated recursively by traverse_all_children
    # traverse_all_children generally called once in main()
    @property
    def size_all_children(self):
        if self._total_size_all_contents > -1:
            return self._total_size_all_contents
        self.traverse_all_children()
        return self._total_size_all_contents

    @property
    def all_children_count(self):
        if self._all_children_count > -1:   # already set (only do once)
            return self._all_children_count
        self.traverse_all_children()
        return self._all_children_count

    def traverse_all_children(self):
        self._total_size_all_contents = 0
        self._all_children_count = 0
        for child in self.child_folders:
            self._total_size_all_contents += child.size_all_children
            self._all_children_count += child.all_children_count

        self._total_size_all_contents += self.size_of_direct_children
        self._all_children_count += self.num_direct_children

    # Additional recursive property. This could probably be built into a
    # single call with traverse_all_children if we traverse the right way.
    @property
    def depth(self):
        if self._depth > -1:    # already set (only do once)
            return self._depth

        depth = 0
        current_node = self
        while not current_node.is_orphan and not current_node.is_root:
            depth += 1
            current_node = current_node.parent
        return depth


# A dictionary of Folders
# id => Folder
# A dictionary with a few new features. Not implemented in the prettiest way
# Todo: this class is poorly named and a suboptimal way to organize this code
class FolderTracker:
    def __init__(self):
        self.data : Dict[str, Folder] = dict()

    # Look up without creation of a new folder if one doesn't exist
    def static_folder_lookup(self, folder_id, none_is_okay=False) -> Optional[Folder]:
        look_up_result = self.data.get(folder_id, None)
        if not look_up_result and not none_is_okay:
            raise Exception("Folder not found in static_folder_lookup: %s" % folder_id)
        return look_up_result

    # Look up and initialize
    def get_folder_or_initialize(self, folder_id) -> Folder:
        if folder_id in self.data:
            return self.data[folder_id]
        else:
            # Initialize a new folder with zero child_folders, since we've never seen it before
            new_folder = Folder(folder_id)
            self.data[folder_id] = new_folder
            return new_folder

    # Records the file. 1) Logs in enclosing parent folder; 2) If this is a folder,
    # then creates folder for this file
    # This handles items the first time we see them
    # Todo: this should not be in this class. Logic duplicated with _do_lookup_from_drive
    def log_item(self, file: GoogleDriveFile) -> NoReturn:
        file_id = SafeFile.safe_get(file, 'id')
        is_a_folder = SafeFile.is_folder(file)
        parent_id = SafeFile.get_parent_id(file)
        parent_folder = None

        if parent_id is not None:
            # Log this file in its enclosing folder, too
            parent_folder = self.get_folder_or_initialize(parent_id)
            parent_folder.num_direct_children += 1

            filesize = SafeFile.file_size(file)
            parent_folder.size_of_direct_children += int(filesize)

        if is_a_folder:
            # Record the folder info
            folder = self.get_folder_or_initialize(file_id)
            folder.populate_fields_from_file(file, parent_folder)
            # only log a child if the child is itself a folder
            if parent_id is not None:
                parent_folder.child_folders.append(folder)

        # Checks and potentially logs this file to be tracked
        file_to_track = SafeFile.review_and_maybe_generate_tracked_file(file, parent_folder)
        if file_to_track is not None:
            tracked_files[file_id] = file_to_track

    # Postprocessing: recursively fill the paths for all folders
    def populate_all_paths(self):
        for folder in self.data.values():
            _ = folder.full_path

# Run only over a given folder and its children
# May be slower than a normal query, since each child folder will issue a new API call (vs calling with max 500)
def run_with_recursive_look_up(starting_id):
    todo_stack = [starting_id]
    total_all_files = 0
    total_folders = 0
    while len(todo_stack) > 0:
        next_parent = todo_stack.pop()
        q_string = "'" + next_parent + "'" + " in parents and trashed=false"
        query = {'maxResults': 1000, 'q': q_string}
        for file_list in drive.ListFile(query):
            total_all_files += len(file_list)
            print(total_all_files)
            for file in file_list:
                if intense_debug:
                    all_file_set.append(file)
                all_folders.log_item(file)
                if SafeFile.is_folder(file):
                    todo_stack.append(SafeFile.safe_get(file, 'id'))
                    total_folders += 1

    print("Parsed %d files\t %d folders" % (total_all_files, total_folders))

# Normal run - Defaults to all files, omits trash, limits to 1000 results per API call
# Goes until all drive files accessible to user are processed
def run_with_query(query=""):
    # Todo: Consider augmenting query with owner = user
    # Note files will never appear multiple times (verified previously)
    if query == "":
        q_string = "trashed=false"
        query = {'maxResults': max_results_api_setting, 'q': q_string}

    total_all_files = 0
    total_folders = 0
    for file_list in drive.ListFile(query):
        total_all_files += len(file_list)
        print(total_all_files)
        for file in file_list:
            if SafeFile.is_folder(file): total_folders += 1
            all_folders.log_item(file)

    print("Parsed %d files\t %d folders" % (total_all_files, total_folders))

def main():
    # ******* This is the main run *********
    if run_short_debug: run_with_recursive_look_up(tester_id)
    else: run_with_query()

    # Post processing
    all_folders.populate_all_paths()    # Recursively populate full paths. todo: This could be moved to "should_write_output"
    if intense_debug:
        print_set("All files", all_file_set)

    # Outputs
    pp(tracked_files)
    if should_write_output:
        pickle_file = open("pickleoutput.db", "wb")
        pickle.dump(all_folders, pickle_file)
        pickle.dump(tracked_files, pickle_file)
        pickle_file.close()

        with open("csv_tracked_files.csv", "w") as csv_file:
            # Todo: these must be kept the same as tracked_file_csv_info(). Refactor to avoid typing them twice
            csv_columns = ['name', 'id', 'url', 'fullpath', 'all_owners', 'is_folder']
            csv_columns.extend(list(FileProperties.default_dict.keys()))
            writer = csv.DictWriter(csv_file, csv_columns)
            writer.writeheader()
            for file in tracked_files.values():
                writer.writerow(file.tracked_file_csv_info())

        # For writing details of folders
        folders_list = list(all_folders.data.values())
        for f in folders_list:
            f.traverse_all_children()      # Recursively go down the tree from each folder
                                           # To populate depth, total size, and total children count
        folders_list.sort(key=lambda x: x.full_path)

        with open("csv_folder_info.csv", "w") as csv_file:
            csv_columns = ['folder_name', 'id', 'url','fullpath', 'num_children', 'total_size']
            writer = csv.DictWriter(csv_file, csv_columns)
            writer.writeheader()
            for folder in folders_list:
                #todo: consider only counting certain folders
                #todo: move this logic into folder (or move the trackedfile logic out of trackedFile)
                row = {
                    'folder_name' : folder.name,
                    'id' : folder.id,
                    'url' : folder.url,
                    'fullpath' : folder.full_path,
                    'num_children' : folder.all_children_count,
                    'total_size' : folder.size_all_children,
                    'owners' : folder.owners
                }
                writer.writerow(row)


if __name__ == "__main__":
    # Auth login (see also settings.yaml)
    gauth = GoogleAuth()
    gauth.LocalWebserverAuth()
    drive = GoogleDrive(gauth)

    # Data accumulation
    all_folders: FolderTracker = FolderTracker()    # Accumulates all folders during run.
                                                    # Also generates tracked files
    tracked_files: Dict[str, TrackedFile] = dict()  # Accumulates files of interest during run
                                                    # Populated in FolderTracker.log_item()
    all_file_set = []                               # Only for intense debugging; not generally used

    main()
