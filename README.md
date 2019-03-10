A program to query GoogleDrive API and output files that match certain criteria:
- shared
- in spaces = photos
- in spaces = app
- trashed (generally not populated since we omit this in the default query)
- multiple owners (rare)
- a file owned by another user (i.e. shared with the user runnng this program)
- orphan files (those that aren't explicitly in user's drive, or other specified
  root foldres)
- files with multiple parents (rare)
- files with file_size greater than a user specified size

- files with more than one permission (same as shared)
- files with sharing to a group or domain (versus to user or to anyone-anyone is
  by link)
- files with link sharing (those with "anyone" sharing type)

The program will output a CSV summarizing
- all of the above information
- all users / groups / domains with whom the file is shared
- the full path of the file
- whether the file is a folder
- url

It will also output a CSV summarzing all folders, including
- the folder name and path
- url
- total child subfiles of the folder (direct and indirect)
- total size of all child subfiles (direct and indirect)
- all folder owners



/*** Dependencies ***/
This code makes use of pydrive which is a wrapper for querying the google drive
API (including authorization). Users should follow the instructions to setup
pydrive, including enabling Google API authentication.

This code is written to support python 3.6+

/*** Hopeful work ***/
I hope to add
- update yaml
- ability to summarize all orphan files (i.e. create a single orphan "root" node
  for tracking)
- ability to programitcally remove sharing (dry_run and actual_run flags
  provided) with users/ groups/ domains not in a specified whitelist

Possibly add
- ability to track changes to permissions / access over time and remove access
  after permissions have gone unused for a given period
- ability to programitically specify the fields to parse / the conditions


