![USGS](USGS_ID_black.png) ![WIM](wimlogo.png)

# WHISPers Web Services

This is the web services codebase for version 2 of Wildlife Health Information Sharing Partnership event reporting system (the web client application codebase can be found [here](https://github.com/USGS-WiM/whispers)). WHISPers allows users to enter, discover, amd explore wildlife mortality data submitted by partners across North America and verified by trained biologists.

This project was built with Django, Django REST Framework, Celery, and Psycopg2.

#### Installation
*Prerequisite*: Please install Python 3 by following [these instructions](https://wiki.python.org/moin/BeginnersGuide/Download).

*Prerequisite*: Please install PostgreSQL by following [these instructions](https://www.postgresql.org/docs/devel/tutorial-install.html).

*Prerequisite*: Please install Celery and RabbitMQ by following [these instructions](https://docs.celeryproject.org/en/latest/getting-started/first-steps-with-celery.html).

```bash
git clone https://github.com/USGS-WiM/whispersservices.git
cd whispersservices

# install virtualenv
pip3 install virtualenv

# create a virtual environment
virtualenv env

# activate the virtual environment
source /env/bin/activate

# install the project's dependencies
pip3 install -r requirements.txt

# migrate the database
python3 manage.py migrate

# install the custom SQL views in the database
psql -U webapp_whispers -d whispers -f whispers_views.sql

# install RabbitMQ, the message broker used by Celery (which is itself was installed by the prior pip command)
sudo apt-get install rabbitmq-server
```

## Environments
The web services are designed to work very slightly differently between dev, test, and production environments. Environment settings are defined in the settings.py file, the most important of which are `ENVIRONMENT`, `APP_WHISPERS_URL`, `SSL_CERT`, and the various email and database settings, among others.

The settings.py file reads from settings.cfg (to keep sensitive information out of code repositories) so all values should be specified in settings.cfg.

To use Celery in development, run `celery -A whispersservices worker -l info` (note that this no longer seems to work on Windows, and so the `--pool=solo` option should be appeneded to the preceding command).

## Development server

Run `python3 manage.py runserver` for a dev server with live reload. Navigate to `http://localhost:8000/api/`. The web services will automatically reload if you change any of the source files. This will use the development environment configuration.

## Production server

In a production environment (or really, any non-development environment) this Django project should be run through a dedicated web server, likely using the Web Server Gateway Interface [(WSGI)](https://wsgi.readthedocs.io/en/latest/). This repository includes sample configuration files (*.conf in the root folder) for running this project in [Apache HTTP Server](https://docs.djangoproject.com/en/dev/howto/deployment/wsgi/modwsgi/).

Additionally, Celery must be set up as a service or daemon for Django to use it. On Linux (note that Celery is no longer supported on Windows) follow the instructions [here](https://docs.celeryproject.org/en/latest/userguide/daemonizing.html#daemonizing) (also read the docs about how Celery and Django connect [here](https://docs.celeryproject.org/en/latest/django/first-steps-with-django.html#django-first-steps)). For convenience, the necessary documents are in this repository:
* `default_celeryd` (sourced from the [official Celery documentation](https://docs.celeryproject.org/en/latest/userguide/daemonizing.html#example-configuration), note that this file should be saved on the server as `/etc/default/celeryd`)
* `init.d_celeryd` (sourced from the [official Celery repo](https://github.com/celery/celery/blob/master/extra/generic-init.d/celeryd), note that this file should be saved on the server as `/etc/init.d/celeryd`, and its file permissions should be set to 755 (which can be done with the command `sudo chmod 755 /etc/init.d/celeryd`); also register the script to run on boot with the command `sudo update-rc.d celeryd defaults`)

## Authors

* **[Aaron Stephenson](https://github.com/aaronstephenson)**  - *Lead Developer* - [USGS Web Informatics & Mapping](https://wim.usgs.gov/)

See also the list of [contributors](../../graphs/contributors) who participated in this project.

## License

This software is in the Public Domain. See the [LICENSE.md](LICENSE.md) file for details

## Suggested Citation
In the spirit of open source, please cite any re-use of the source code stored in this repository. Below is the suggested citation:

`This project contains code produced by the Web Informatics and Mapping (WIM) team at the United States Geological Survey (USGS). As a work of the United States Government, this project is in the public domain within the United States. https://wim.usgs.gov`


## About WIM
* This project authored by the [USGS WIM team](https://wim.usgs.gov)
* WIM is a team of developers and technologists who build and manage tools, software, web services, and databases to support USGS science and other federal government cooperators.
* WIM is a part of the [Upper Midwest Water Science Center](https://www.usgs.gov/centers/wisconsin-water-science-center).
