#!/bin/bash
set -e

# Should be run after new thonny package is uploaded to PyPi

PREFIX=$HOME/thonny_template_build_37
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"


# prepare working folder #########################################################
rm -rf build
mkdir -p build


# copy template #################################################
cp -R -H $PREFIX/Thonny.app build

# update launch script (might have changed after last create_base_bundle.sh) #####################
cp $SCRIPT_DIR/Thonny.app.initial_template/Contents/MacOS/thonny \
    build/Thonny.app/Contents/MacOS

FRAMEWORKS=build/Thonny.app/Contents/Frameworks
PYTHON_CURRENT=$FRAMEWORKS/Python.framework/Versions/3.7/

# install deps #####################################################
$PYTHON_CURRENT/bin/python3.7  -s -m pip install --no-cache-dir --no-binary mypy -r ../requirements-regular-bundle.txt

# install certifi #####################################################
$PYTHON_CURRENT/bin/python3.7 -s -m pip install --no-cache-dir certifi

# install thonny #####################################################
$PYTHON_CURRENT/bin/python3.7 -s -m pip install --pre --no-cache-dir thonny
rm $PYTHON_CURRENT/bin/thonny # because this contains absolute paths

# clean unnecessary stuff ###################################################

# delete all *.h files except one
#mv $PYTHON_CURRENT/include/python3.7m/pyconfig.h $SCRIPT_DIR # pip needs this
#find $FRAMEWORKS -name '*.h' -delete
#mv $SCRIPT_DIR/pyconfig.h $PYTHON_CURRENT/include/python3.7m # put it back

#find $FRAMEWORKS -name '*.a' -delete

rm -rf $FRAMEWORKS/Tcl.framework/Versions/8.6/Tcl_debug
rm -rf $FRAMEWORKS/Tk.framework/Versions/8.6/Tk_debug
rm -rf $FRAMEWORKS/Tk.framework/Versions/8.6/Resources/Scripts/demos
rm -rf $FRAMEWORKS/Tcl.framework/Versions/8.6/Resources/Documentation
rm -rf $FRAMEWORKS/Tk.framework/Versions/8.6/Resources/Documentation

find $PYTHON_CURRENT/lib -name '*.pyc' -delete
find $PYTHON_CURRENT/lib -name '*.exe' -delete
rm -rf $PYTHON_CURRENT/Resources/English.lproj/Documentation

rm -rf $PYTHON_CURRENT/share
rm -rf $PYTHON_CURRENT/lib/python3.7/test
rm -rf $PYTHON_CURRENT/lib/python3.7/idlelib


rm -rf $PYTHON_CURRENT/lib/python3.7/site-packages/pylint/test
rm -rf $PYTHON_CURRENT/lib/python3.7/site-packages/mypy/test

# clear bin because its scripts have absolute paths
mv $PYTHON_CURRENT/bin/python3.7 $SCRIPT_DIR # save python exe
rm -rf $PYTHON_CURRENT/bin/*
mv $SCRIPT_DIR/python3.7 $PYTHON_CURRENT/bin/

# create pip
# NB! check that pip.sh refers to correct executable!
cp $SCRIPT_DIR/../pip.sh $PYTHON_CURRENT/bin/pip3.7

# create linkns ###############################################################
cd $PYTHON_CURRENT/bin
ln -s python3.7 python3
ln -s pip3.7 pip3
cd $SCRIPT_DIR




# copy the token signifying Thonny-private Python
cp thonny_python.ini $PYTHON_CURRENT/bin 


# Replace Python.app Info.plist to get name "Thonny" to menubar
cp -f $SCRIPT_DIR/Python.app.plist $PYTHON_CURRENT/Resources/Python.app/Contents/Info.plist

# version info ##############################################################
VERSION=$(<$PYTHON_CURRENT/lib/python3.7/site-packages/thonny/VERSION)
ARCHITECTURE="$(uname -m)"
VERSION_NAME=thonny-$VERSION-$ARCHITECTURE 


# set version ############################################################
sed -i.bak "s/VERSION/$VERSION/" build/Thonny.app/Contents/Info.plist
rm -f build/Thonny.app/Contents/Info.plist.bak

# sign frameworks and app ##############################
codesign -s "Marc Evanstein" --timestamp --keychain ~/Library/Keychains/login.keychain-db \
	--entitlements thonny.entitlements --options runtime \
	build/Thonny.app/Contents/Frameworks/Python.framework
codesign -s "Marc Evanstein" --timestamp --keychain ~/Library/Keychains/login.keychain-db \
	--entitlements thonny.entitlements --options runtime \
	build/Thonny.app

# add readme #####################################################################
cp readme.txt build

# add a scamp folder, copy the examples into it, and the update script
mkdir build/SCAMP
cp Setup.command build/SCAMP
cp .UpdateExamples.sh build/SCAMP
cp .UpdateSCAMP.sh build/SCAMP
cp .RemoveQuarantine.sh build/SCAMP
# move the Thonny app into it
mv build/Thonny.app build/SCAMP/Thonny.app
cd build/SCAMP
ln -s Thonny.app/Contents/Frameworks/Python.framework/Versions/3.7/lib/python3.7/site-packages/soundfonts/ Soundfonts
