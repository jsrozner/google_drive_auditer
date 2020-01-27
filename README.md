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

/*** How it works ***/
See dependencies below, and for a more details summary of code's control flow,
see the "Brief readme note" in the googdrivecheck.py file near the top.



/*** Dependencies ***/
This code makes use of pydrive which is a wrapper for querying the google drive
API (including authorization). Users should follow the instructions to setup
pydrive, including enabling Google API authentication.

In particular, see https://github.com/gsuitedevs/PyDrive, and make sure you've
downloaded client_secrets.json, as well as updated the config.yaml file
appropriately (it should be renamed from example_settings.yaml ->
settings.yaml).

This code is written to support python 3.6+

/*** SETUP ***/
(Following the instructions from the pydrive github linked above):
1) Go to console.developers.google.com, create an OAuth 2.0 client ID (this
enables you to use the API to query your own account).

2) Download the created API token and save as "client_secrets.json"
(Note: .gitignore, which shoudl have been downloaded when you cloned, ignores.
.json (client_secrets.json and saved_credientials.json), as well as
settings.yaml, which also has your private key)

3) Rename example_settings.yaml => settings.yaml. Update the fields:
- my_user_name
- rootdirs (if you have or do not have additional roots, you might remove "My
  Computer" or add another name)
- see #4 below. Otherwise nothing else needs to be changed from the defaults
name.

4) From the client_secrets.json that you downloaded, copy your "client_id" and "client_secret" into settings.yaml, where they are specified.

5) Run python3 googdrivecheck.py (make sure you have all other dependencies
satisifed from import statements: e.g., typing, csv, pickle, yaml).
If you have downloaded pydrive and gotten your client_secrets correctly, then
you should have a browser window that opens and asks you to sign into google.)
- you will see "this app isn't verified". The unverified app is the oauth token
  that you created for yourself (only you have access, so you're granting access
  to yourself here). After that, the actual code that will query this API is the
  code that you run locally (this file that you're running.). You can of course
  read through the code to make sure that it does what you expect it to do.
  After you are okay with all of this, click

  "show advanced" > go to goodriveaudit"

- grant permission to see edit, create, delete. (The app won't do any deletion
  or modificiations). Again, this grants access to you to make these changes via
  the code that you're running locally.

- continue through the authentication flow

5.5) If you get a credential error of the form "invalid_grant: bad request", try
deleting your saved_credentials.json. The program should regenerate it.

6) You should begin to see logging notes as the API works.

6.5) If you get an HTTP error in a pydrive call, just try rerunning the program.
Ideally I would handle these in the python execution and just retry.

7) CSV files will be generated in the same dir that you can then examine.

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



