import os
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


class MFZipFile(ZipFile):
    """
    ZipFile modified to preserve file attributes.
    https://stackoverflow.com/questions/39296101/python-zipfile-removes-execute-permissions-from-binaries
    """

    def extract(self, member, path=None, pwd=None):
        """

        Parameters
        ----------
        member : str
            individual file to extract. If member does not exist, all files
            are extracted.
        path : str
            directory path to extract file in a zip file (default is None,
            which results in files being extracted in the current directory)
        pwd : str
            zip file password (default is None)

        Returns
        -------
        ret_val : int
            return value indicating status of file extraction

        """
        if not isinstance(member, ZipInfo):
            member = self.getinfo(member)

        if path is None:
            path = os.getcwd()

        ret_val = self._extract_member(member, str(path), pwd)
        attr = member.external_attr >> 16
        if attr != 0:
            os.chmod(ret_val, attr)

        return ret_val

    def extractall(self, path=None, members=None, pwd=None):
        """Extract all files in the zipfile.

        Parameters
        ----------
        path : str
            directory path to extract files in a zip file (default is None,
            which results in files being extracted in the current directory)
        members : str
            individual files to extract (default is None, which extracts
            all members)
        pwd : str
            zip file password (default is None)

        Returns
        -------

        """
        if members is None:
            members = self.namelist()

        if path is None:
            path = os.getcwd()
        else:
            if hasattr(os, "fspath"):
                # introduced in python 3.6 and above
                path = os.fspath(str(path))

        for zipinfo in members:
            self.extract(zipinfo, str(path), pwd)

    @staticmethod
    def compressall(path, file_pths=None, dir_pths=None, patterns=None):
        """Compress selected files or files in selected directories.

        Parameters
        ----------
        path : str
            output zip file path
        file_pths : str or list of str
            file paths to include in the output zip file (default is None)
        dir_pths : str or list of str
            directory paths to include in the output zip file (default is None)
        patterns : str or list of str
            file patterns to include in the output zip file (default is None)

        Returns
        -------
        success : bool
            boolean indicating if the output zip file was created

        """

        # create an empty list
        if file_pths is None:
            file_pths = []
        # convert files to a list
        else:
            if isinstance(file_pths, str):
                file_pths = [file_pths]
            elif isinstance(file_pths, tuple):
                file_pths = list(file_pths)

        # remove directories from the file list
        if len(file_pths) > 0:
            file_pths = [e for e in file_pths if os.path.isfile(e)]

        # convert dirs to a list if a str (a tuple is allowed)
        if dir_pths is None:
            dir_pths = []
        else:
            if isinstance(dir_pths, str):
                dir_pths = [dir_pths]

        # convert find to a list if a str (a tuple is allowed)
        if patterns is not None:
            if isinstance(patterns, str):
                patterns = [patterns]

        # walk through dirs and add files to the list
        for dir_pth in dir_pths:
            for dirname, subdirs, files in os.walk(dir_pth):
                for filename in files:
                    fpth = os.path.join(dirname, filename)
                    # add the file if it does not exist in file_pths
                    if fpth not in file_pths:
                        file_pths.append(fpth)

        # remove file_paths that do not match the patterns
        if patterns is not None:
            tlist = []
            for file_pth in file_pths:
                if any(p in os.path.basename(file_pth) for p in patterns):
                    tlist.append(file_pth)
            file_pths = tlist

        # write the zipfile
        success = True
        if len(file_pths) > 0:
            zf = ZipFile(path, "w", ZIP_DEFLATED)

            # write files to zip file
            for file_pth in file_pths:
                arcname = os.path.basename(file_pth)
                zf.write(file_pth, arcname=arcname)

            # close the zip file
            zf.close()
        else:
            msg = "No files to add to the zip file"
            print(msg)
            success = False

        return success


def zip_all(path, file_pths=None, dir_pths=None, patterns=None):
    """
    Compress all files in the user-provided list of file paths and directory
    paths that match the provided file patterns.

    Parameters
    ----------
    path : str
        path of the zip file that will be created
    file_pths : str or list
        file path or list of file paths to be compressed
    dir_pths : str or list
        directory path or list of directory paths to search for files that
        will be compressed
    patterns : str or list
        file pattern or list of file patterns s to match to when creating a
        list of files that will be compressed

    Returns
    -------

    """
    return MFZipFile.compressall(path, file_pths=file_pths, dir_pths=dir_pths, patterns=patterns)
