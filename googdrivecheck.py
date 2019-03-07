from pydrive.auth import GoogleAuth
from pydrive.drive import GoogleDrive

from pprint import pprint as pp
from typing import List

import pickle


# Util function
def is_folder(file):
    return file['mimeType'] == "application/vnd.google-apps.folder"

class Folder:
    def __init__(self, file_id, parent=None, name=""):
        # These two must always be set
        self.id = file_id
        self.num_children = 0

        # These two might be set later
        self.name = name
        self.parent = parent

        # This is set after all files are parsed
        self.full_path = None

    # Name and parent may be set once the folder is discovered
    def set_name_and_parent(self, name, parent):
        if self.name != "":
            print("error: name is already set")
        if self.parent is not None:
            print("error: parent is already set")

        self.name = name
        self.parent = parent

    def increment_child_count(self):
        self.num_children += 1

    def set_full_path(self, path):
        if self.full_path is not None:
            print("full path already set")
            print("full path was %s" % self.full_path)
            print("new full path is %s" % path)
        self.full_path = path

    def __repr__(self):
        return " ".join("{}={!r}".format(k, v) for k, v in self.__dict__.items())


# A dictionary of Folders
# id => Folder
class FolderTracker:
    def __init__(self):
        self.data = dict()

    # Look up without creation of a new folder if one doesn't exist
    def static_folder_lookup(self, folder_id):
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

    def log_item(self, file):
        file_id = file['id']
        name = file['title']
        parents = file['parents']
        if len(parents) == 0:
            print("no parents - potentially a shared orphan file")
            return

        parent = parents[0]['id']
        if(len(parents)) > 1:
            print("more than one parent")
        is_a_folder = is_folder(file)

        if is_a_folder:
            # Record the folder info
            folder = self._get_folder_or_initialize(file_id)
            folder.set_name_and_parent(name, parent)

        # Log this file in its enclosing folder, too
        enclosing_folder = self._get_folder_or_initialize(parent)
        enclosing_folder.increment_child_count()


    def get_full_path(self, folder: Folder):
        #print("getting path for folder in get_full_path")
        #pp(folder)
        # Quick fail if we've already done this node
        if folder.full_path is not None:
            #print("already had full path for folder")
            return folder.full_path

        # Base case: no more parents
        if folder.parent is None:
            #print("%s is a root node" % folder.name)

            if folder.name == "":
                #print("this folder was never seen. Setting name to ??")
                folder.set_full_path("??")
            return folder.full_path

        # Otherwise, we go fetch the parent
        #print("looking up the parent")
        parent = self.static_folder_lookup(folder.parent)
        if parent is None:
            #print("we never saw this parent")
            # We never actually saw this folder (started at non root level)
            full_path = ".../" + folder.name
            #print("path is: %s" % full_path)
            folder.set_full_path(full_path)
            return full_path

        #print("parent is not none: recursing")
        full_path = self.get_full_path(parent) + "/" + folder.name
        folder.set_full_path(full_path)
        return full_path


    def populate_all_paths(self):
        for folder in self.data.values():
            #print("*** getting path for folder")
            #pp(folder)
            if folder.full_path is None:
                self.get_full_path(folder)

def print_set(set_name, file_set: List):
    print("** Printing set: %s" % set_name)
    for file in file_set:
        parent_folder_id = file['parents'][0]['id']
        parent_folder = all_folders.static_folder_lookup(parent_folder_id)
        parent_folder_path = all_folders.get_full_path(parent_folder)
        file['fullpath'] = parent_folder_path + "/" + file['title']

    file_set.sort(key=lambda x: x['fullpath'])
    pp([x['fullpath'] for x in file_set])


def check_file_sharing(file):
    if "photos" in file["spaces"]:
        spaces_photos_set.append(file)
    elif "appDataFolder" in file["spaces"]:
        spaces_app_data_folder_set.append(file)

    if file['labels']['trashed']:
        trash_set.append(file)


    has_a_problem = False
    shared = False
    more_than_one_permission = False
    link_sharing = False

    # Special errors
    if len(file['owners']) > 1:
        has_a_problem = True
        more_than_one_owner_set.append(file)

    if not "Josh Rozner" in file['ownerNames']:
        not_owned_by_me_set.append(file)
        has_a_problem = True

    # End special errors

    # Sharing info
    """
    if len(file['permissionIds']) > 1:
        print("more than one permission ID")
        more_than_one_permission_set.append(file)
        has_a_problem = True

    if "anyoneWithLink" in file['permissionsIds']:
        print("link sharing enabled")
        link_sharing_set.append(file)
        has_a_problem = True
    
    try:
        if len(file['permissions']) > 1:
            print("more than one permission ID")
            more_than_one_permission_set.append(file)
            more_than_one_permission = True

        for permission in file['permissions']:
            permission_type = permission['value']['type']
            if permission_type != "user":
                print("non user permission type: %s" % permission_type)
                link_sharing = True
                link_sharing_set.append(file)
    except:
        pp(file)
    # Some verifications:
    if bool(shared) ^ bool(more_than_one_permission):
        print("inconcistency in shared and permission count")

    if bool(link_sharing) ^ bool(shared):
        print("inconsistency in shared and link sharing")
    """

    if file['shared']:
        sharing_set.append(file)
        shared = True
        print("file is shared")




if __name__ == "__main__":
    # Auth login (see also settings.yaml)
    gauth = GoogleAuth()
    gauth.LocalWebserverAuth()
    drive = GoogleDrive(gauth)

    # Data accumulation
    all_folders = FolderTracker()

    # tracking sets
    spaces_photos_set = []
    spaces_app_data_folder_set = []

    not_owned_by_me_set = []
    trash_set = []
    more_than_one_owner_set = []

    #link_sharing_set = []
    #more_than_one_permission_set = []
    sharing_set = []

    all_file_set = []


    total_files = 0
    # Note: already verified this does not have duplicates
    #todo: make sure owner is josh, not in trash
    """
    todo_stack = ["0B4aSdoErkE3vfnp2Mi0zYTBVVWhETHBkalA3eUJkN3JCNXlLaUtRSGxuckRKZ05vNTBRdVk"]

    while len(todo_stack) > 0:
        next_parent = todo_stack.pop()
        q_string = "'" + next_parent + "'" + " in parents and trashed=false"
        query = {'maxResults': 1000, 'q': q_string}
        #simple_query = {'maxResults': 1000}
        for file_list in drive.ListFile(query):
            #pp(file_list)
            total_files += len(file_list)
            print(total_files)
            for f in file_list:
                #all_file_set.append(f)
                all_folders.log_item(f)
                check_file_sharing(f)
                if is_folder(f):
                    todo_stack.append(f['id'])
    """
    q_string = "trashed=false"
    query = {'maxResults': 1000, 'q': q_string}
    for file_list in drive.ListFile(query):
        total_files += len(file_list)
        print(total_files)
        for f in file_list:
            #all_file_set.append(f)
            all_folders.log_item(f)
            check_file_sharing(f)
    print(total_files)
    all_folders.populate_all_paths()
    #pp(all_folders)


    #print_set("All files", all_file_set)
    print_set("Shared files", sharing_set)
    #print_set("Link sharing", link_sharing_set)
    #print_set("More than one user has access", more_than_one_permission_set)

    print_set("Not owned by me", not_owned_by_me_set)
    print_set("In trash", trash_set)
    print_set("More than one owner", more_than_one_owner_set)
    print_set("Spaces: photos", spaces_photos_set)
    print_set("Spaces: app data", spaces_app_data_folder_set)

    pickle_file = open("pickleoutput.db", "wb")
    pickle.dump(sharing_set, pickle_file)
    pickle.dump(not_owned_by_me_set, pickle_file)
    pickle.dump(trash_set, pickle_file)
    pickle.dump(more_than_one_owner_set, pickle_file)
    pickle.dump(spaces_photos_set, pickle_file)
    pickle.dump(spaces_app_data_folder_set, pickle_file)
    pickle.dump(all_folders, pickle_file)
    pickle_file.close()


    # todo: see where all the massive file set is hidden