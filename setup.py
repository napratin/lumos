import os
from setuptools import setup, find_packages

# Setup flags and parameters
do_install_scripts = False  # enable this to install useful scripts in /usr/[local/]bin/

# Look for OpenCV
try:
  import cv2
  print "setup.py: [INFO] OpenCV version: {} (2.4.x+ should work fine)".format(cv2.__version__)
except ImportError:
  print "setup.py: [WARNING] OpenCV library not found; please install from: http://opencv.org/"

# Cache readme contents for use as long_description
readme = open('README.md').read()

# Find executable scripts to be installed, if desired
scripts = []
if do_install_scripts:
  script_path = os.path.join('foocv', 'tools')
  scripts = [os.path.join(script_path, script) for script in os.listdir(script_path) if script.endswith('.py') and not script == '__init__.py']
  print "setup.py: [INFO] Scripts to be installed: {}".format(", ".join(scripts))

# Call setup()
setup(
  name='foocv',
  version='0.1',
  description='Computer vision tools and utility codebase (depends on OpenCV)',
  long_description=readme,
  url='https://github.com/napratin/foocv',
  author='Arpan Chakraborty',
  author_email='napratin@yahoo.co.in',
  license='MIT',
  packages=find_packages(),
  install_requires=[
    'numpy',
    'pyzmq'
  ],
  test_suite='foocv.tests',
  scripts=scripts,
  include_package_data=True,
  zip_safe=False,
  platforms='any',
  keywords='computer vision active vision video camera image processing utilities tools codebase framework',
  classifiers=[
    'Development Status :: 3 - Alpha',
    'Intended Audience :: Developers',
    'Intended Audience :: End Users/Desktop',
    'Intended Audience :: Education',
    'Intended Audience :: Science/Research',
    'License :: OSI Approved :: MIT License',
    'Programming Language :: Python :: 2.7',
    'Operating System :: OS Independent',
    'Topic :: Scientific/Engineering :: Artificial Intelligence',
    'Topic :: Scientific/Engineering :: Image Recognition',
    'Topic :: Multimedia :: Video :: Display',
    'Topic :: Multimedia :: Video :: Capture',
    'Topic :: Software Development :: Libraries :: Python Modules',
    'Topic :: Utilities'
  ])
