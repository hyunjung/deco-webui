# Copyright 2012 Stanford University InfoLab
# See LICENSE for details.

import re

from setuptools import setup


version = re.search("^__version__ = '(.*)'",
                    open('deco_webui/__init__.py').read(), re.M).group(1)

setup(
    name='deco-webui',
    version=version,
    description='Deco: A System for Declarative Crowdsourcing',
    author='Stanford InfoLab',
    author_email='deco@cs.stanford.edu',
    url='http://infolab.stanford.edu/deco/',
    packages=['deco_webui'],
    entry_points="""
        [console_scripts]
        deco-webui = deco_webui.wsgiapp:main
        """,
    include_package_data=True,
    zip_safe=False,
    install_requires=[
        'beaker==1.6.4',
        'bottle==0.11.6',
        'deco',
        'gevent-websocket==0.3.6',
        'jinja2==2.7'],
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: BSD License',
        'Operating System :: OS Independent',
        'Programming Language :: Python :: 2.7',
        'Topic :: Database :: Front-Ends'],
)
