from __future__ import annotations
from pprint import pprint as pp
from typing import List, Optional
import pickle

from pydrive.auth import GoogleAuth
from pydrive.drive import GoogleDrive

def lazy_property_folder_metadata(fn):
    """Decorator for lazily fetching certain metadata"""
    @property
    def _lazy_property(self: Folder):
        if not self._seen:
            self._do_lookup_from_drive()
        if self._metadata_lookup_failed:
            print("Metadata lookup unsuccessful. Default value returned for %s" + fn.__repr__)
        return fn(self)
    return _lazy_property

# Todo
intense_debug = False
debug = False

# Todo
# Drive defines "My Drive" as root, but backed up computers are not captured.
rootdirs = ["My Drive", "My MacBook Air"]
orphan_prefix = "0_orphan"
name_for_non_seeable_folders = "no_name"

# Util functions
def is_folder(file):
    return file['mimeType'] == "application/vnd.google-apps.folder"
def is_root_folder(file):
    return file['title'] in rootdirs and len(file['parents']) == 0
def print_file_note(description_string, file):
    print("file_note: " + description_string + ("\n title: %s\t id:%s" % (file['title'], file['id'])))

# Fetches the first parent's ID.
# Returns None if no parent
# Prints notice if more than one parent
def get_parent(file):
    parent_array = file['parents']
    if len(parent_array) == 0:
        return None

    if(len(parent_array)) > 1:
        print("** more than one parent")

    return parent_array[0]['id']

# Simple class to initialize a dictionary of the properties we want to track
class FileProperties:
    @classmethod
    def get_default_properties(cls):
        default_dict = {
            "shared" : False,
            "spaces_photo" : False,
            "spaces_app" : False,
            "trashed" : False,
            "multi_owners" : False,
            "non_auth_user_file" : False,
            "has_more_than_one_permission" : False,
            "has_non_user_permission" : False,
            "has_link_sharing" : False
        }
        return default_dict

# A file that has a property we care about. Files without interesting properties are not tracked
# After being initialized, everything can be safely accessed. Generally set once and then read upon output
class TrackedFile:
    def __init__(self, file, properties_dictionary: dict):
        self.file = file
        self.props = properties_dictionary
        self.non_user_owners = []

        if properties_dictionary['non_auth_user_file']:
            self.non_user_owners = list(x['displayName'] for x in file['owners'])

        # Metadata fetch is expensive, so
        # Only fetch sharing for files owned by us (if not owned by us, of course it's shared!) and that are shared
        if not properties_dictionary['non_auth_user_file'] and properties_dictionary['shared']:
            self._fetch_sharing_metadata()

    def __repr__(self):
        return self.file['title'] + "\n" + self.props.__repr__()

    def _fetch_sharing_metadata(self):
        file = self.file
        is_shared = self.props['shared']

        # Some magic in case fetching fails
        fetch_success = False
        fetch_try_count = 0
        while not fetch_success and fetch_try_count < 5:
            try:
                file.FetchMetadata(fetch_all=True)
                fetch_success = True
                if fetch_try_count > 0:
                    print("fetch success after %d tries" % fetch_try_count)
                break
            except Exception:
                if fetch_try_count == 0:
                    print("error fetching metadata for title: %s\t id: %s" % (file['title'], file['id']))
                    print(str(Exception))
                fetch_try_count += 1

        # Fail early if all fetches failed
        if not fetch_success:
            print("fetches failed %d times. Abandoning" % fetch_try_count)
            return

        has_more_than_one_permission = False   # This is not particularly useful
        has_non_user_permission = False        # This in general will match link_sharing, except in rare cases
        has_link_sharing = False

        if len(file['permissions']) > 1:
            self.props['has_more_than_one_permission'] = True

        permission_type_list = \
            list([[perm['type'],perm.get('emailAddress')] for perm in file['permissions'] if perm['type'] != "user"])
        if "anyone" in permission_type_list:
            self.props['has_link_sharing'] = True

        # todo: prettier way?
        for permission in permission_type_list:
            if permission[0] not in ['anyone']:
                print_file_note("non user or anyone permission type", file)
                pp(permission_type_list)
                self.props['has_non_user_permission'] = True
                break

        # Some verifications based on our expectations of how sharing works.
        if has_non_user_permission:
            assert(has_more_than_one_permission and is_shared)
        # Check that it's shared if any of the three conditions are met
        if has_more_than_one_permission or has_non_user_permission or has_link_sharing:
            assert is_shared
        # If link sharing, then it has multiple permissions and one is non sharing
        if has_link_sharing:
            assert(has_more_than_one_permission and has_non_user_permission and is_shared)

# Represents an individual folder (a file type). Basically behaves like a tree node.
class Folder:
    def __repr__(self):
        return " ".join("{}={!r}".format(k, v) for k, v in self.__dict__.items())

    def __init__(self, file_id):
        # These two are always set and safe to read
        self.id = file_id
        self.num_direct_children = 0    # This is incremented during processing. Early fetches may be wrong
        self.child_folders = []         # Same as above

        # Whether file has been explicitly processed
        self._seen = False      # Set to true when name is parsed; Indicates whether this folder has been
                                # explicitly seen by metadata / get() fetch
        self._metadata_lookup_failed = False

        # Properties (looked up lazily and protected by property method). Default values below.
        # Guarded by self._seen
        self._is_orphan = False  # Could be wrong if lookup failed
        self._is_root = False    # Could be wrong if lookup failed
        self._full_path = None   # Generally set during post-processing. Lazily fetched
        self._name = ""          # Set by file lookup. Lazily fetched
        self._parent = None      # Set by file lookup. Lazily fetched

        # True post processing (last traverse of tree). If these values differ from -1, then have been set
        self._all_children_count = -1   # count of all individual subchildren (through subdirectories to end)
        self._depth = -1

    # Populates all fields for the folder.
    def populate_fields_from_file(self, file, parent):
        if self._seen:
            raise Exception("Fields have already been populated once")
        if self._metadata_lookup_failed:
            raise Exception("Metadata lookup failed. Invalid call to populate fields")
        self._seen = True

        self._name = file['title']
        self._parent = parent

        if self._parent is None:
            if is_root_folder(file): self._is_root = True
            else: self._is_orphan = True

    # Do a google drive lookup and fill the normal fields
    def _do_lookup_from_drive(self):
        if self._seen or self._metadata_lookup_failed:
            return

        file_to_fetch = None
        try:
            # We try to fetch the data for this file
            file_to_fetch = drive.CreateFile({'id': self.id})
            print("fetched metadata for %s" % file_to_fetch['title'])

            parent_id = get_parent(file_to_fetch)
            parent_folder = None
            if parent_id is not None:
                parent_folder = Folder(parent_id)

            # We also create a parent folder for this file
            self.populate_fields_from_file(file_to_fetch, parent=parent_folder)
        except Exception:
            print("error trying to fetch folder %s" % self.id)
            print(str(Exception))
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
            # This file is not "see-able". Fall back to a "...". The folder.name here should not be populated.
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
            print("*** ERROR *** no parent (and not root or orphan) for id: %s" % self.id)

        return self._full_path

    # Properties that require full metadata
    @lazy_property_folder_metadata
    def name(self):
        return self._name
    @lazy_property_folder_metadata
    def parent(self):
        return self._parent
    @lazy_property_folder_metadata
    def is_orphan(self):
        return self._is_orphan
    @lazy_property_folder_metadata
    def is_root(self):
        return self._is_root

    # Post processing. Both functions are recursive and iterate through all folders.
    @property
    def all_children_count(self):
        if self._all_children_count > -1:   # already set (only do once)
            return self._all_children_count
        self._all_children_count = 0

        # Otherwise, iterate through the child_folders
        for child in self.child_folders:
            self._all_children_count += child.get_all_children_count()
        self._all_children_count += self.num_direct_children

        return self._all_children_count

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
class FolderTracker:
    def __init__(self):
        self.data = dict()

    # Look up without creation of a new folder if one doesn't exist
    def static_folder_lookup(self, folder_id) -> Optional[Folder]:
        look_up_result = self.data.get(folder_id)
        if not look_up_result:
            raise Exception("Folder not found in static_folder_lookup: %s" % folder_id)
        return look_up_result

    # Look up and initialize
    def _get_folder_or_initialize(self, folder_id):
        if folder_id in self.data:
            return self.data[folder_id]
        else:
            # Initialize a new folder with zero child_folders, since we've never seen it before
            new_folder = Folder(folder_id)
            self.data[folder_id] = new_folder
            return new_folder

    # Records the file. 1) Logs in enclosing parent folder; 2) If this is a folder,
    # then creates folder for this file
    def log_item(self, file):
        file_id = file['id']
        is_a_folder = is_folder(file)
        parent = get_parent(file)
        parent_folder = None

        if parent is not None:
            # Log this file in its enclosing folder, too
            parent_folder = self._get_folder_or_initialize(parent)
            parent_folder.num_direct_children += 1

        if is_a_folder:
            # Record the folder info
            folder = self._get_folder_or_initialize(file_id)
            folder.populate_fields_from_file(file, parent=parent_folder)
            # only log a child if the child is itself a folder
            if parent is not None:
                parent_folder.child_folders.append(folder)

    # Postprocessing: recursively fill the paths for all folders
    def populate_all_paths(self):
        for folder in self.data.values():
            _ = folder.full_path

def print_set(set_name, file_set: List):
    print("** Printing set: %s" % set_name)
    for file in file_set:
        parent_folder_id = get_parent(file)
        if parent_folder_id is None:
            file['fullpath'] = orphan_prefix + "/" + file['title']
        else:
            parent_folder = all_folders.static_folder_lookup(parent_folder_id)
            parent_folder_path = parent_folder.full_path
            file['fullpath'] = parent_folder_path + "/" + file['title']

    file_set.sort(key=lambda x: x['fullpath'])
    pp([x['fullpath'] for x in file_set])


def check_file_sharing(file):
    file_id = file['id']
    properties_dict = FileProperties.get_default_properties()

    if file['shared']:
        properties_dict['shared'] = True

    if "photos" in file["spaces"]:
        properties_dict['spaces_photo'] = True
    elif "appDataFolder" in file["spaces"]:
        properties_dict['spaces_app'] = True

    if file['labels']['trashed']:
        properties_dict['trashed'] = True
        print_file_note("file is trashed", file)

    if len(file['owners']) > 1:
        properties_dict['multi_owners'] = True
        print_file_note("file has multi owners", file)

    if not "Josh Rozner" in file['ownerNames']:
        properties_dict['non_auth_user_file'] = True

    if True in properties_dict.values():
        tracked_files[file_id] = TrackedFile(file, properties_dict)

def run_with_recursive_look_up(starting_id):
    #todo_stack = [""]
    todo_stack = [starting_id]
    total_files = 0
    total_folders = 0
    while len(todo_stack) > 0:
        next_parent = todo_stack.pop()
        q_string = "'" + next_parent + "'" + " in parents and trashed=false"
        query = {'maxResults': 1000, 'q': q_string}
        for file_list in drive.ListFile(query):
            total_files += len(file_list)
            print(total_files)
            for f in file_list:
                if intense_debug:
                    all_file_set.append(f)
                all_folders.log_item(f)
                check_file_sharing(f)
                if is_folder(f):
                    todo_stack.append(f['id'])
                    total_folders += 1

    print("Parsed %d files\t %d folders" % total_all_files, total_folders)
    return total_files, total_folders

def run_with_query(query=""):
    if query == "":
        q_string = "trashed=false"
        query = {'maxResults': 1000, 'q': q_string}

    total_all_files = 0
    total_folders = 0
    for file_list in drive.ListFile(query):
        total_all_files += len(file_list)
        print(total_all_files)
        for f in file_list:
            if is_folder(f): total_folders += 1
            all_folders.log_item(f)
            check_file_sharing(f)

    print("Parsed %d files\t %d folders" % total_all_files, total_folders)
    return total_all_files, total_folders

if __name__ == "__main__":
    # Auth login (see also settings.yaml)
    gauth = GoogleAuth()
    gauth.LocalWebserverAuth()
    drive = GoogleDrive(gauth)

    # Data accumulation
    all_folders = FolderTracker()   # Accumulates all folders during run
    tracked_files = dict()           # Accumulates files of interest during run

    all_file_set = []       # Only for intense debugging; not generally used

    #todo: make sure owner is josh, not in trash
    # todo Note: already verified this does not have duplicates

    # ******* This is the main run *********
    run_with_recursive_look_up("0B4aSdoErkE3vTHRTdzRzOTBIR3M") # "active"
    #run_with_query()

    # Post processing
    all_folders.populate_all_paths()
    if intense_debug:
        print_set("All files", all_file_set)

    pp(tracked_files)

    should_write = True
    if should_write:
        pickle_file = open("pickleoutput.db", "wb")
        pickle.dump(all_folders, pickle_file)
        pickle.dump(tracked_files, pickle_file)
        pickle_file.close()
