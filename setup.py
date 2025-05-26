from setuptools import setup, find_packages

setup(
    name='infractl',
    version='0.1.0',
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        'typer[all]',
        'fastapi',
        'uvicorn',
        'kubernetes',
        'ansible',
        'ansible-runner',
        'python-dotenv',
        'requests'
    ],
    entry_points={
        'console_scripts': [
            'infractl=infractl.cli:app'
        ]
    },
    author='Your Name',
    description='A full-featured CLI and API toolkit for Kubernetes GitOps lifecycle automation',
    classifiers=[
        'Programming Language :: Python :: 3',
        'Operating System :: OS Independent',
    ],
    python_requires='>=3.8',
)
