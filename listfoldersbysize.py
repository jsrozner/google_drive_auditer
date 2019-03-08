import pickle
import sys

from googdrivecheck import Folder, FolderTracker
from typing import List

def get_all_children_count(folder: Folder):
    # If this folder is already set, then just return
    if folder.all_children_count > 0:
        return folder.all_children_count

    # Otherwise, iterate through the children
    for f in folder.children:
        folder.all_children_count += get_all_children_count(f)
    return folder.all_children_count + folder.num_direct_children

def print_folders(folders: List[Folder]):
    print("** Printing folders:")
    folders.sort(key=lambda x: x.full_path)

    for x in folders:
        if x.all_children_count > 1000:
            print("%s\t%d" % (x.full_path, x.all_children_count))

if __name__ == "__main__":
    pf = open(sys.argv[1], "rb")
    #pf = open("./pickleoutput.db")
    shared = pickle.load(pf)
    not_owned_by_me = pickle.load(pf)
    trash_set = pickle.load(pf)
    more_than_one_owner_set = pickle.load(pf)
    spaces_photo_set = pickle.load(pf)
    spaces_app_data_set = pickle.load(pf)
    all_folders: FolderTracker = pickle.load(pf)

    folder_list = list(all_folders.data.values())
    for f in folder_list:
        get_all_children_count(f)

    print_folders(folder_list)
