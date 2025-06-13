#!/usr/bin/env python3
"""Setup script for the RKE2 installer package."""

from setuptools import setup, find_packages

with open('README.md', 'r', encoding='utf-8') as f:
    long_description = f.read()

setup(
    name="rke2-installer",
    version="0.1.0",
    description="Modular RKE2 cluster installer and manager",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Emodo Infrastructure Team",
    author_email="infra@emodo.com",
    url="https://github.com/emodoinc/infra",
    packages=find_packages(where="..", include=["rke2.installer*"]),
    package_dir={"": ".."},
    python_requires=">=3.8",
    install_requires=[
        'pyyaml>=5.3.1',
        'paramiko>=2.7.2',
        'typing-extensions>=3.7.4.3',
        'tenacity>=7.0.0',
    ],
    extras_require={
        'dev': [
            'pytest>=6.2.2',
            'pytest-cov>=2.11.1',
            'mypy>=0.812',
            'black>=21.5b2',
            'isort>=5.8.0',
            'flake8>=3.9.2',
        ],
    },
    entry_points={
        'console_scripts': [
            'rke2-installer=rke2.installer.__main__:main',
        ],
    },
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Intended Audience :: System Administrators',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Topic :: System :: Systems Administration',
        'Topic :: System :: Clustering',
    ],
    keywords='rke2 kubernetes cluster installer',
)
