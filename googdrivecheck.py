from __future__ import annotations
from pprint import pprint as pp
from typing import Dict, List, NoReturn, Optional
import csv
import pickle

from pydrive.auth import GoogleAuth
from pydrive.drive import GoogleDrive, GoogleDriveFile

def lazy_property_folder_metadata(fn: function):
    """Decorator for lazily fetching certain metadata"""
    @property
    def _lazy_property(self: Folder):
        if not self._seen:
            self._do_lookup_from_drive()
        if self._metadata_lookup_failed:
            print("Metadata lookup unsuccessful. Yield default. File: %s\t, metadata: %s\t, id: %s" %
                  (self._name, fn.__name__, self.id))
        return fn(self)
    return _lazy_property

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

# Simple class to initialize a dictionary of the properties we will track
# Todo: prevent adding new properties (e.g. by wrong name ref)
class FileProperties:
    default_dict : Dict[str,bool] = {
        # These are accessed set in SafeFile.review_and_maybe_track()
        "shared" : False,
        "spaces_photo" : False,
        "spaces_app" : False,
        "trashed" : False,
        "multi_owners" : False,
        "non_auth_user_file" : False,
        "is_orphan" : False,
        "has_multiple_parents" : False, #todo

        # These are set in TrackedFile._fetch_metadata() (only called if shared = True)
        "has_more_than_one_permission" : False,
        "has_non_user_permission" : False,
        "has_link_sharing" : False,
    }

class SafeFile:
    """ Use this class to access fields in GoogleDriveFile, in case API ever changes
    Any special drive-like fields that are API dependent should be contained here.
    """
    property_mapping = {
        'name' : 'title',
        'id' : 'id',
        'mimeType' : 'mimeType',
        'owners' : 'owners',
        'ownerNames' : 'ownerNames',
        'url' : 'alternateLink',
        'permissions' : 'permissions',
        'shared' : 'shared',

        # Special properties
        '_safe_parents': 'parents',
        '_spaces': 'spaces'

        # Special properties that are not fetched with safe_get()
        # fileSize
        # labels
    }
    @classmethod
    def safe_get(cls, file: GoogleDriveFile, item: str, issue_warning_if_not_present=True):
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
    def special_permissions_list(cls, file:GoogleDriveFile) -> List[List[str]]:
        permissions = SafeFile.safe_get(file, 'permissions')
        return list([perm['type'],perm.get('emailAddress')]
                    for perm in permissions if perm['type'] not in ["user", "anyone"])

    @classmethod
    def file_size(cls, file:GoogleDriveFile) -> int:
        #FileSize is not populated for google docs
        file_size = SafeFile.safe_get(file, 'fileSize', issue_warning_if_not_present=False)
        if file_size is None:
            file_size = 0
        return file_size

    @classmethod
    def review_and_maybe_track(cls, file: GoogleDriveFile, parent: 'Folder'):
        file_id = SafeFile.safe_get(file, "id")
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

        if True in properties_dict.values():
            tracked_files[file_id] = TrackedFile(file, properties_dict, parent)


class TrackedFile:
    """A file that has a property we care about. Files without interesting properties are not tracked (save space)
        After being initialized, everything can be safely accessed. Generally set once and then read upon output
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
        output_dict = self.props.copy()
        output_dict['name'] = SafeFile.safe_get(self.file,'name')
        output_dict['id'] = SafeFile.safe_get(self.file, 'id')
        output_dict['url'] = SafeFile.safe_get(self.file, 'url')
        output_dict['fullpath'] = SafeFile.get_full_path(self.file, self.parent_folder)
        output_dict['non_user_owners'] = SafeFile.get_all_owners(self.file)
        output_dict['is_folder'] = SafeFile.is_folder(self.file)
        return output_dict

    # Internal method called only for files that are not owned by us and that are shared.
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
        has_non_user_permission = False        # This in general will match link_sharing, except in rare cases
        has_link_sharing = False

        if len(SafeFile.safe_get(file, 'permissions')) > 1:
            self.props['has_more_than_one_permission'] = True

        special_permissions_info = SafeFile.special_permissions_list(file)
        if len(special_permissions_info) > 0:
            print_file_note("non user-anyone permission type", file)
            pp(special_permissions_info)
            self.props['has_non_user_permission'] = True

        if SafeFile.has_link_sharing(file):
            self.props['has_link_sharing'] = True

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

    def __init__(self, file_id: str):
        # These two are always set and safe to read
        self.id = file_id
        self.num_direct_children = 0    # This is incremented during processing. Early fetches may be wrong
        self.size_of_direct_children = 0# Same as above
        self.child_folders: List[Folder] = []         # Same as above

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
        self._parent_folder = None      # Set by file lookup. Lazily fetched
        self._url = ""

        # True post processing (last traverse of tree). If these values differ from -1, then have been set
        self._all_children_count = -1   # count of all individual subchildren (through subdirectories to end)
        self._size_all_children = -1
        self._depth = -1

    # Populates all fields for the folder.
    def populate_fields_from_file(self, file: GoogleDriveFile, parent_folder: 'Folder'):
        if self._seen:
            raise Exception("Fields have already been populated once")
        if self._metadata_lookup_failed:
            raise Exception("Metadata lookup failed. Invalid call to populate fields")
        self._seen = True

        self._name = SafeFile.safe_get(file, 'name')
        self._parent_folder = parent_folder
        self._url = SafeFile.safe_get(file, 'url')

        if self._parent_folder is None:
            if SafeFile.is_root_folder(file): self._is_root = True
            else: self._is_orphan = True

    # Do a google drive lookup and fill the normal fields
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
                parent_folder = Folder(parent_id)

            # We also create a parent folder for this file
            self.populate_fields_from_file(file_to_fetch, parent_folder)
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

    # Post processing. Both functions are recursive and iterate through all folders.
    @property
    def size_all_children(self):
        if self._size_all_children > -1:
            return self._size_all_children
        self.traverse_all_children()
        return self._size_all_children

    @property
    def all_children_count(self):
        if self._all_children_count > -1:   # already set (only do once)
            return self._all_children_count
        self.traverse_all_children()
        return self._all_children_count

    def traverse_all_children(self):
        self._size_all_children = 0
        self._all_children_count = 0
        for child in self.child_folders:
            self._size_all_children += child.size_all_children
            self._all_children_count += child.all_children_count

        self._size_all_children += self.size_of_direct_children
        self._all_children_count += self.num_direct_children

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
# This
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
    def _get_folder_or_initialize(self, folder_id) -> Folder:
        if folder_id in self.data:
            return self.data[folder_id]
        else:
            # Initialize a new folder with zero child_folders, since we've never seen it before
            new_folder = Folder(folder_id)
            self.data[folder_id] = new_folder
            return new_folder

    # Records the file. 1) Logs in enclosing parent folder; 2) If this is a folder,
    # then creates folder for this file
    def log_item(self, file: GoogleDriveFile) -> NoReturn:
        file_id = SafeFile.safe_get(file, 'id')
        is_a_folder = SafeFile.is_folder(file)
        parent = SafeFile.get_parent_id(file)
        parent_folder = None

        if parent is not None:
            # Log this file in its enclosing folder, too
            parent_folder = self._get_folder_or_initialize(parent)
            parent_folder.num_direct_children += 1

            filesize = file.get('fileSize', 0)
            parent_folder.size_of_direct_children += int(filesize)

        if is_a_folder:
            # Record the folder info
            folder = self._get_folder_or_initialize(file_id)
            folder.populate_fields_from_file(file, parent_folder)
            # only log a child if the child is itself a folder
            if parent is not None:
                parent_folder.child_folders.append(folder)

        SafeFile.review_and_maybe_track(file, parent_folder) # Checks and potentially logs this file to be tracked

    # Postprocessing: recursively fill the paths for all folders
    def populate_all_paths(self):
        for folder in self.data.values():
            _ = folder.full_path

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

def run_with_query(query=""):
    # Todo: Consider augmenting query with owner = user
    # Note files will never appear multiple times (verified previously)
    if query == "":
        q_string = "trashed=false"
        query = {'maxResults': 1000, 'q': q_string}

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
    all_folders.populate_all_paths()
    if intense_debug:
        print_set("All files", all_file_set)

    pp(tracked_files)
    if should_write_output:
        pickle_file = open("pickleoutput.db", "wb")
        pickle.dump(all_folders, pickle_file)
        pickle.dump(tracked_files, pickle_file)
        pickle_file.close()

        with open("csv_tracked_files.csv", "w") as csv_file:
            csv_columns = ['name', 'id', 'url', 'fullpath', 'non_user_owners', 'is_folder']
            csv_columns.extend(list(FileProperties.default_dict.keys()))
            writer = csv.DictWriter(csv_file, csv_columns)
            writer.writeheader()
            for file in tracked_files.values():
                writer.writerow(file.tracked_file_csv_info())

        folders_list = list(all_folders.data.values())
        for f in folders_list:
            f.traverse_all_children()
        folders_list.sort(key=lambda x: x.full_path)

        with open("csv_folder_info.csv", "w") as csv_file:
            csv_columns = ['folder_name', 'id', 'url','fullpath', 'num_children', 'total_size']
            writer = csv.DictWriter(csv_file, csv_columns)
            writer.writeheader()
            for folder in folders_list:
                #todo: only count certain foldres
                row = {
                    'folder_name' : folder.name,
                    'id' : folder.id,
                    'url' : folder.url,
                    'fullpath' : folder.full_path,
                    'num_children' : folder.all_children_count,
                    'total_size' : folder.size_all_children
                }
                writer.writerow(row)


if __name__ == "__main__":
    # Auth login (see also settings.yaml)
    gauth = GoogleAuth()
    gauth.LocalWebserverAuth()
    drive = GoogleDrive(gauth)

    # Data accumulation
    all_folders: FolderTracker = FolderTracker()    # Accumulates all folders during run
    tracked_files: Dict[str, TrackedFile] = dict()  # Accumulates files of interest during run
    all_file_set = []                               # Only for intense debugging; not generally used

    main()
