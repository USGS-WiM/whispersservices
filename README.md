# WHISPers Web Services

Written in Python 3.6 using Django 2.1, Django REST Framework 3.8.2, and Psycopg2 2.7.5

### Requirements
Python3

### Installing project

Clone the repo onto your location machine and step into the project.

```git clone https://github.com/USGS-WiM/whispers.git```

```cd whispersservices_django.settings```

Ensure your settings.py and other credentials are correct.

### Installing Virtual Env & Packages
Using Pip, install VirtualEnv (https://packaging.python.org/guides/installing-using-pip-and-virtualenv/) & create a virtual environment.

```py -m pip install --user virtualenv```

```py -m virtualenv env```

Activate the virtual env and use pip to install the packages listed in the `requirements.txt` file.

```.\env\Scripts\activate```

```pip install {package==version}```

Run the server

```python manage.py runserver```