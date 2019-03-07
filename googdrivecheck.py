from pydrive.auth import GoogleAuth
from pydrive.drive import GoogleDrive

from pprint import pprint as pp

from typing import List




# Util function
def is_folder(file):
    return file['mimeType'] == "application/vnd.google-apps.folder"


class Folder:
    def __init__(self, id, parent=None, name=""):
        # These two must always be set
        self.id = id
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
        if self.parent != None:
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
class FolderTracker():
    def __init__(self):
        self.data = dict()


    def static_folder_lookup(self, id):
        look_up_result = self.data.get(id)
        if not look_up_result:
            print("error not found")
            return None

        return look_up_result

    def _get_folder_or_initialize(self, folder_id):
        if folder_id in self.data:
            return self.data[folder_id]
        else:
            # Initialize a new folder with zero children, since we've never seen it before
            new_folder = Folder(folder_id)
            self.data[folder_id] = new_folder
            return new_folder

    def log_item(self, file):
        id = file['id']
        name = file['title']
        parents = file['parents']
        parent = parents[0]['id']
        if(len(parents)) > 1:
            print("more than one parent")
        is_a_folder = is_folder(file)

        if is_a_folder:
            # Record the folder info
            folder = self._get_folder_or_initialize(id)
            folder.set_name_and_parent(name, parent)

        # Log this file in its enclosing folder, too
        enclosing_folder = self._get_folder_or_initialize(parent)
        enclosing_folder.increment_child_count()


    def get_full_path(self, folder: Folder):
        print("getting path for folder in get_full_path")
        pp(folder)
        # Quick fail if we've already done this node
        if folder.full_path is not None:
            print("already had full path for folder")
            return folder.full_path

        # Base case: no more parents
        if folder.parent is None:
            print("%s is a root node" % folder.name)

            if folder.name == "":
                print("this folder was never seen. Setting name to ??")
                folder.set_full_path("??")
            return folder.full_path

        # Otherwise, we go fetch the parent
        print("looking up the parent")
        parent = self.static_folder_lookup(folder.parent)
        if parent is None:
            print("we never saw this parent")
            # We never actually saw this folder (started at non root level)
            full_path = ".../" + folder.name
            print("path is: %s" % full_path)
            folder.set_full_path(full_path)
            return full_path

        print("parent is not none: recursing")
        full_path = self.get_full_path(parent) + "/" + folder.name
        folder.set_full_path(full_path)
        return full_path


    def populate_all_paths(self):
        for folder in self.data.values():
            print("*** getting path for folder")
            pp(folder)
            if folder.full_path is None:
                self.get_full_path(folder)

def print_set(set: List):
    for f in set:
        parent_folder_id = f['parents'][0]['id']
        parent_folder = all_folders.static_folder_lookup(parent_folder_id)
        parent_folder_path = all_folders.get_full_path(parent_folder)
        f['fullpath'] = parent_folder_path + "/" + f['title']

    set.sort(key=lambda x: x['fullpath'])
    pp([x['fullpath'] for x in set])

def check_file_sharing(file):
    if "photos" in file["spaces"]:
        spaces_photos_set.append(file)
    elif "appDataFolder" in file["spaces"]:
        spaces_app_data_folder_set.append(file)

    if file['labels']['trashed']:
        trash_set.append(file)


    has_a_problem = False
    # Special errors
    if len(file['owners']) > 1:
        has_a_problem = True
        more_than_one_owner_set.append(file)

    if not "Josh Rozner" in file['owners']:
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
    """

    if file['shared']:
        has_a_problem = True
        sharing_set.append(file)
        print("file is shared")

    return has_a_problem


if __name__ == "__main__":
    gauth = GoogleAuth()
    gauth.LocalWebserverAuth()
    drive = GoogleDrive(gauth)

    all_folders = FolderTracker()


    # tracking sets
    spaces_photos_set = []
    spaces_app_data_folder_set = []

    not_owned_by_me_set = []
    trash_set = []
    more_than_one_owner_set = []

    more_than_one_permission_set = []
    sharing_set = []
    link_sharing_set = []

    all_file_set = []


    total = 0
    # Note: already verified this does not have duplicates
    #todo: make sure owner is josh, not in trash
    todo_stack = ["1v_NC1Q2bla71bnfJ2rCl7HySPvubu1e5"]

    while len(todo_stack) > 0:
        next_parent = todo_stack.pop()
        q_string = "'" + next_parent + "'" + " in parents"
        query = {'maxResults': 1000, 'q': q_string}
        #simple_query = {'maxResults': 1000}
        for file_list in drive.ListFile(query):
            pp(file_list)
            total += len(file_list)
            print(total, flush=True)
            for f in file_list:
                all_file_set.append(f)
                all_folders.log_item(f)
                check_file_sharing(f)
                if is_folder(f):
                    todo_stack.append(f['id'])

    print(total)
    all_folders.populate_all_paths()

    pp(all_folders)

    print_set(sharing_set)
    print_set(all_file_set)


