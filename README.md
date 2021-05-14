A program to query GoogleDrive API and output files that match certain criteria:
- shared
- in spaces = photos
- in spaces = app
- trashed (generally not populated since we omit this in the default query)
- multiple owners (rare)
- a file owned by another user (i.e. shared with the user running this program)
- orphan files (those that aren't explicitly in user's drive, or other specified
  root folders)
- files with multiple parents (rare)
- files with `file_size` greater than a user specified size in `settings.yaml`
- files with more than one permission (same as shared)
- files with sharing to a group or domain (versus to user or to anyone-anyone by a link)
- files with link sharing (those with "anyone" sharing type)
- (If you want to change this, see the method
  `review_and_maybe_generate_tracked_file`, which determines which files to track
  and then output).

The program will output a CSV summarizing
- all the above information
- all users / groups / domains with whom the file is shared
- the full path of the file
- whether the file is a folder
- url

It will also output a CSV summarizing all folders, including
- the folder name and path
- url
- total child sub-files of the folder (direct and indirect)
- total size of all child sub-files (direct and indirect)
- all folder owners

/*** How it works ***/
See dependencies below, and for a more details summary of code's control flow,
see the "Brief readme note" in the `googdrivecheck.py` file near the top.



/*** Dependencies ***/
All dependencies are in `Pipfile` and `Pipfile.lock`, You will need to run `pipenv install` to get
all the dependencies. Read about `pipenv` in https://realpython.com/pipenv-guide/

This code makes use of `pydrive` which is a wrapper for querying the Google Drive
API (including authorization). Users should follow the instructions to set up
`pydrive`, including enabling Google API authentication.

In particular, see https://github.com/gsuitedevs/PyDrive, and make sure you've
downloaded `client_secrets.json`, as well as updated the `settings.yaml` file
appropriately (it should be renamed from `example_settings.yaml` ->
`settings.yaml`).

This code is written to support python 3.6+

/*** SETUP ***/
(Following the instructions from the pydrive github linked above):
1) Go to [console.developers.google.com](https://console.developers.google.com/apis/credentials).

1) Create an `OAuth 2.0 client ID` (this enables you to use the API to query your own account).

1) Download the created API token and save as `client_secrets.json`.
   Note: `client_secrets.json` must be kept secret, hence `.gitignore` file has `.json` to make sure
   it is not saved in the code history or uploaded to GitHub. The same applies to
   `saved_credentials.json` (which is automatically generated) and `settings.yaml`, which also has
   your private key.

1) Rename example_settings.yaml => settings.yaml.

1) Update the following fields in `settings.yaml`:
   
   | Name | Description |
   |------|-------------|
   | `client_id` | From the `client_secrets.json` file that you downloaded |
   | `client_secret` | From the `client_secrets.json` file that you downloaded |
   | `my_user_name` | The name and last name (not the email address) shown in your Google Account, i.e: "Joe Doe" |
   | `rootdirs` | if you have or do not have additional roots, you might remove "My Computer" or add another name |
   | `oauth_scope` | Drive API v3 Scopes - This restricts the permissions to your Google Drive files |

1) Run `python3 googdrivecheck.py` (make sure you have all dependencies in `Pipfile` are
satisfied. e.g., typing, csv, pickle, yaml). 

1) If you have downloaded `pydrive` and gotten your `client_secrets.json` correctly, then you should
   have a browser window that opens and asks you to sign in to Google.

1) You will see `this app isn't verified`. The unverified app is the oauth token
   that you created for yourself (only you have access, so you're granting access
   to yourself here). After that, the actual code that will query this API is the
   code that you run locally (the `googdrivecheck.py` file that you're running.). You can of course
   read through the code to make sure that it does what you expect it to do.

1) After you are okay with all of this, click show `Advanced > go to googdriveaudit`

1) Grant permissions specified by the `oauth_scope` list in the `settings.yaml` file. By default,
   only metadata can be read (file name, file permissions, etc. but no file content).
   (The app won't do any deletion or modifications). Again, this grants access to you to make these
   changes via the code that you're running locally.
    1) If you get a credential error of the form `invalid_grant: bad request`, try deleting your 
       `saved_credentials.json`. `googdriveaudit.py` should regenerate it.

    1) It is possible you haven't activated the Drive API in your GCP Project.
       ``` 
       "Access Not Configured. Drive API has not been used in project YOUR_PROJECT_NUMBER before or it is disabled. 
       Enable it by visiting https://console.developers.google.com/apis/api/drive.googleapis.com/overview?project=YOUR_PROJECT_NUMBER then retry. 
       If you enabled this API recently, wait a few minutes for the action to propagate to our systems and retry."
      ```

1) You should begin to see logging entries in the terminal, as the API works.

    1) If you get an HTTP error in a pydrive call, just try rerunning the program. Ideally I would
       handle these in the python execution and just retry.

1) Report CSV files `csv_folder_info.csv` and `csv_tracked_files.csv` will be generated in the same 
   directory where `googdriveaudit.py` is.

1) The kinds of tracked files can be filtered. See method `review_and_maybe_generate_tracked_file`. 

/*** Hopeful work ***/
I hope to add
- update yaml
- ability to summarize all orphan files (i.e. create a single orphan "root" node
  for tracking)
- ability to programmatically remove sharing (dry_run and actual_run flags
  provided) with users/ groups/ domains not in a specified whitelist

Possibly add
- ability to track changes to permissions / access over time and remove access
  after permissions have gone unused for a given period
- ability to programmatically specify the fields to parse / the conditions



