from pprint import pprint as pp
from typing import List
import pickle

from pydrive.auth import GoogleAuth
from pydrive.drive import GoogleDrive

from typing import Optional

# Todo
intense_debug = False
debug = False

# Todo
# Drive defines "My Drive" as root, but backed up computers are not captured.
rootdirs = ["My Drive", "My MacBook Air"]
orphan_prefix = "0_orphan"

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

    def __init__(self, file_id, parent=None, name=""):
        # These two are always set and safe to read
        self.id = file_id
        self.num_direct_children = 0

        # These may be set later
        self.parent = parent    # Of type folder
        self.children = []

        self.is_orphan = False
        self.is_root = False
        self.seen = False       # Set to true when name is parsed; Indicates whether this folder has been
                                # explicitly seen by metadata / get() fetch
        self.depth = 0          # Todo: populate depth

        # Updated during post-processing
        self.metadata_lookup_failed = False
        # This is set after all files are parsed
        self.all_children_count = 0   # count of all files and subfolders

        # Properties
        self._full_path = None  # Generally set during post-processing
        self._name = name

    # Name and parent may be set once the folder is discovered
    def initialize_from_file(self, file, parent):
        if self.name != "":
            print("error: name is already set")
        if self.parent is not None:
            print("error: parent is already set")

        self.name = file['title']
        self.seen = True
        self.parent = parent

        is_root = is_root_folder(file)
        if is_root: self.is_root = True
        else: self.is_orphan = True

    def increment_child_count(self):
        self.num_direct_children += 1

    def add_child(self, child):
        self.children.append(child)

    # Recursively lookup fullpaths through the folder tree
    @property
    def full_path(self):
        # Quick fail if we've already done this node
        if self._full_path is not None:
            return self._full_path

        # If we never encountered this folder before, then we walk up the folder tree doing lookups
        # In a single function call, this should populate the current folder's parent
        if not self.seen and not self.metadata_lookup_failed:
            print("fetching metadata for %s" % self.id)
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
                self.initialize_from_file(file_to_fetch, parent=parent_folder)

            except Exception:
                print("error trying to fetch folder")
                print(str(Exception))
                pp(file_to_fetch)
                pp(self)
                self.metadata_lookup_failed = True

                # This file is not "see-able". Fall back to a "...". The folder.name here should not be populated.
                full_path = ".../" + self.name
                self._full_path = full_path
                return full_path

        # Base case: no more parents
        # If we are here, there are no more parents because it is root, orphaned, or error
        full_path = ""
        if self.parent is None:
            if self.is_root:
                full_path = self.name
            elif self.is_orphan:
                full_path = orphan_prefix + "/" + self.name
            # Else it's a metadata lookup failure
            # We should never get here, since metadata lookup failures already set the fullpath
            else:
                print("*** ERROR *** no parent (and not root or orphan) for id: %s" % self.id)

            self._full_path = full_path
            return full_path

        # Otherwise recursively fetch
        self._full_path = self.parent.full_path + "/" + self.name
        return self._full_path

    # todo: make sure name is populated (by fetch)
    # remove self.seen lookup?
    @property
    def name(self):
        return self._name
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
            print("error not found")
            return None

        return look_up_result

    # Look up and initialize
    def _get_folder_or_initialize(self, folder_id):
        if folder_id in self.data:
            return self.data[folder_id]
        else:
            # Initialize a new folder with zero children, since we've never seen it before
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
            parent_folder.increment_child_count()

        if is_a_folder:
            # Record the folder info
            folder = self._get_folder_or_initialize(file_id)
            folder.initialize_from_file(file, parent=parent_folder)
            # only log a child if the child is itself a folder
            if parent is not None:
                parent_folder.add_child(folder)

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

    return total_files

def run_with_query(query=""):
    if query == "":
        q_string = "trashed=false"
        query = {'maxResults': 1000, 'q': q_string}

    total_files = 0
    for file_list in drive.ListFile(query):
        total_files += len(file_list)
        print(total_files)
        for f in file_list:
            #all_file_set.append(f)
            all_folders.log_item(f)
            check_file_sharing(f)

    return total_files

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
