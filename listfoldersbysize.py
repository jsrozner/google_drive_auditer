import pickle
import sys

from googdrivecheck import Folder, FolderTracker
from typing import List


def print_folders(folders: List[Folder]):
    print("** Printing folders:")
    folders.sort(key=lambda x: x.full_path)

    for x in folders:
        if x.all_children_count > 1000:
            print("%s\t%d" % (x.full_path, x.all_children_count))


if __name__ == "__main__":
    pf = open(sys.argv[1], "rb")
    # pf = open("./pickleoutput.db")
    all_folders: FolderTracker = pickle.load(pf)
    folder_list = list(all_folders.data.values())
    for f in folder_list:
        f.all_children_count()

    print_folders(folder_list)