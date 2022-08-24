# Changelog

## [v2.2.1](https://github.com/USGS-WiM/whispersservices/releases/tag/v2.2.1) - 2022-08-24

### Fixed

- Fix bug in standard notification emailing caused by off-by-one list pop

## [v2.2.0](https://github.com/USGS-WiM/whispersservices/releases/tag/v2.2.0) - 2022-08-17

### Added

- Implement new business rule for Event Diagnosis behavior when Event complete status is changed:
- When a complete event is changed to incomplete and the event diagnosis is Undetermined, that event diagnosis can stay if it was manually set by a user, otherwise if it was automatically set by the application then it must be deleted and replaced by a Pending event diagnosis.
- Add source template ID to Notification records

### Changed

- Allow multiple event diagnoses even if one is Undetermined
- Wrap requests json parsing in narrow Try-Except block, and change outer Try-Except block to use generic exception
- Refactor handling of Undetermined and Pending Event Diagnoses

### Fixed

- Fix bug where Service Request Response change was not sending email due to using a user ID instead of email address

## [v2.1.12](https://github.com/USGS-WiM/whispersservices/releases/tag/v2.1.12) - 2022-01-27

### Changed

- Ensure inactive users do not receive Service Request Response or Comment notifications

## [v2.1.11](https://github.com/USGS-WiM/whispersservices/releases/tag/v2.1.11) - 2022-01-26

### Changed

- Implement workaround in event change detection for notifications to adjust for an apparent bug in simple_history module that ignores stored timezone in datetimes
- Ensure Stale Event notifications are only sent to active users
- Ensure inactive users do not receive Collaborator Alert Notifications
- Ensure a population_count of 0 triggers a validation error
- Ensure admins get notifications for comment and contact creates and updates

### Fixed

- Fix bug in LocationSpecies population_count validation
- Fix bug in location species validation by testing for nulls
- Fix bug in location species validation by testing for nulls that evaluate to zero

## [v2.1.10](https://github.com/USGS-WiM/whispersservices/releases/tag/v2.1.10) - 2021-12-16

### Fixed

- Fix bug in "All Events" updated notifications for admin users.

## [v2.1.9](https://github.com/USGS-WiM/whispersservices/releases/tag/v2.1.9) - 2021-11-05

### Changed

- Change EventSummaries serializer field list determination to be based solely on role.

## [v2.1.8](https://github.com/USGS-WiM/whispersservices/releases/tag/v2.1.8) - 2021-10-21

### Fixed

- Fix bug in flyway email message generator caused by bad variable reference

## [v2.1.7](https://github.com/USGS-WiM/whispersservices/releases/tag/v2.1.7) - 2021-09-21

### Changed

- Ensure inactive users are excluded from verify_email response (to populate collaborator lists) and from notifications (where possible)
- Rearrange flyway determination code to ensure Hawaii is properly assigned even when lat/lng is null
- Change Circles queryset so that admins and superadmins only see circles from their own org, rather than all circles
- Allow "Quality Check Needed" notifications to be created during an event create

### Fixed

- Fix bug in priority field recalculation when modified_by field is null
- Fix bug in custom notifications caused by queryset annotations when using "AND" operator

## [v2.1.6](https://github.com/USGS-WiM/whispersservices/releases/tag/v2.1.6) - 2021-07-20

### Fixed

- Fix bug in EventSummaries where a GET (one) request was returning multiple events and raising an error

## [v2.1.5](https://github.com/USGS-WiM/whispersservices/releases/tag/v2.1.5) - 2021-07-02

### Fixed

- Fix bug in EventDetailSerializer.get_organizations caused by trying to access attribute from None

## [v2.1.4](https://github.com/USGS-WiM/whispersservices/releases/tag/v2.1.4) - 2021-06-23

### Changed

- Change handling of lat/lng validations (warning emails sent to admins instead of errors sent to users), and several bug fixes

## [v2.1.3](https://github.com/USGS-WiM/whispersservices/releases/tag/v2.1.3) - 2021-04-06

### Changed

- Change EventLocation lat/lng validation from an error sent to user to a warning sent to admins and allow record creation process to proceed

## [v2.1.2](https://github.com/USGS-WiM/whispersservices/releases/tag/v2.1.2) - 2021-03-24

### Changed

- Dynamically read API version from code.json into openapi schema and docs on app load

### Fixed

- Fix bugs in event location validation where expected ADM2 was not present in Geonames response (instead received PPL), and admin level two name matching using exact match gave unexpected results (change to use contains match)

## [v2.1.1](https://github.com/USGS-WiM/whispersservices/releases/tag/v2.1.1) - 2021-03-23

### Changed

- Update celery init.d file to work with Celery 5.0.x

### Fixed

- Fix bug where superadmin and admin could not set event to complete

## [v2.1.0](https://github.com/USGS-WiM/whispersservices/releases/tag/v2.1.0) - 2021-03-22

### Added

- Implement New User Email Confirmation and Password Reset

## [v2.0.20](https://github.com/USGS-WiM/whispersservices/releases/tag/v2.0.20) - 2021-03-12

### Fixed

- Fix bug in lat+lng--country+admin1+admin2 validation where admin2 lookup was not using admin1 for uniqueness, causing erroneous matching

## [v2.0.19](https://github.com/USGS-WiM/whispersservices/releases/tag/v2.0.19) - 2021-03-11

### Changed

- Improve protections when calling third party services to prevent short-circuiting of business rules in event creation

## [v2.0.18](https://github.com/USGS-WiM/whispersservices/releases/tag/v2.0.18) - 2021-01-27

### Fixed

- Fix bug introduced by last bug fix, bad lookup on Event object in child Event Details serializers

## [v2.0.17](https://github.com/USGS-WiM/whispersservices/releases/tag/v2.0.17) - 2021-01-26

### Fixed

- Fix bug in event detail and child serializers caused by looking up wrong model type

## [v2.0.16](https://github.com/USGS-WiM/whispersservices/releases/tag/v2.0.16) - 2021-01-22

### Fixed

- Fix object lookup bug in some detail serializers

## [v2.0.15](https://github.com/USGS-WiM/whispersservices/releases/tag/v2.0.15) - 2021-01-20

### Changed

- Properly check permissions (include parent event ownership, not just current object ownership) when determining serializer fields

### Fixed

- Fix permissions check bug that did not check parent event ownership
- Fix priority calculation bugs caused by fields not specified in aggregate functions

## [v2.0.14](https://github.com/USGS-WiM/whispersservices/releases/tag/v2.0.14) - 2021-01-11

### Changed

- Allow admins to see all new and updated events in the nightly 'ALL Events' notifications, regardless of public status or owner/org/collaborator status
- Rephrase validation errors for edits when event is complete

## [v2.0.13](https://github.com/USGS-WiM/whispersservices/releases/tag/v2.0.13) - 2021-01-06

### Fixed

- Fix bug in Organization validation PATCHes without ID values
- Fix bug in Event Collaborator update
- Fix missing object permissions problem in Search model

## [v2.0.12](https://github.com/USGS-WiM/whispersservices/releases/tag/v2.0.12) - 2020-12-23

### Changed

- Prevent event owner from adding self to collaborator lists (silently ignore)
- Change service request response notification to have source be response_by value not modified_by
- Restore intended behavior for Contact GETs to only return active contacts unless otherwise specified

## [v2.0.11](https://github.com/USGS-WiM/whispersservices/releases/tag/v2.0.11) - 2020-11-20

### Fixed

- Fix bug caused by premature auto-adding request_response value to new service request object within new event creation

## [v2.0.10](https://github.com/USGS-WiM/whispersservices/releases/tag/v2.0.10) - 2020-11-20

### Fixed

- Fix diagnosis_string definitions in serializers to return model property that already auto-appends 'suspect' when appropriate

## [v2.0.9](https://github.com/USGS-WiM/whispersservices/releases/tag/v2.0.9) - 2020-11-06

### Fixed

- Fix bug in details serializers caused by omitting admin user checks

## [v2.0.8](https://github.com/USGS-WiM/whispersservices/releases/tag/v2.0.8) - 2020-11-06

### Changed

- Ensure EventDetails include nested EventLocation comments and contacts
- Allow public role users to name their own searches

## [v2.0.7](https://github.com/USGS-WiM/whispersservices/releases/tag/v2.0.7) - 2020-10-30

### Changed

- Reset scheduled_tasks 'yesterday' variable to correct value

## [v2.0.6](https://github.com/USGS-WiM/whispersservices/releases/tag/v2.0.6) - 2020-10-30

### Fixed

- Fix bug introduced in stale events notification task during refactor
- Fix bug in custom notification task that caused duplicate notifications

## [v2.0.5](https://github.com/USGS-WiM/whispersservices/releases/tag/v2.0.5) - 2020-10-20

### Changed

- Re-enable ordering/sorting for all endpoints to fix oversight in refactor

## [v2.0.4](https://github.com/USGS-WiM/whispersservices/releases/tag/v2.0.4) - 2020-10-16

### Changed

- Define EventGroupSerializer name field explicity so it works with the new dynamic field list

## [v2.0.3](https://github.com/USGS-WiM/whispersservices/releases/tag/v2.0.4) - 2020-10-16

### Fixed

- Fix view ordering bug from refactor

## [v2.0.2](https://github.com/USGS-WiM/whispersservices/releases/tag/v2.0.4) - 2020-10-16

### Changed

- Restore missing 'diagnosis_string' and 'cause_string' fields to relevant serializers.

## [v2.0.1](https://github.com/USGS-WiM/whispersservices/releases/tag/v2.0.4) - 2020-10-16

### Fixed

- Fix bug in ServiceRequest comment not auto-assigning diagnostic comment type

## [v2.0.0](https://github.com/USGS-WiM/whispersservices/releases/tag/v2.0.4) - 2020-10-16

### Added

- Notifications and API Docs

## [v1.5.0](https://github.com/USGS-WiM/whispersservices/releases/tag/v1.5.0) - 2020-03-30

### Added

- Include "public" field in all Event Summary requests for authenticated users and CSV export for same users
- For Event Summary list requests (GET all), allow authenticated users to see both public events and any private events that those users otherwise have permission to see, instead of only public events

## [v1.5.0](https://github.com/USGS-WiM/whispersservices/releases/tag/v1.5.0) - 2020-03-30

### Changed

- Include "public" field in all Event Summary requests for authenticated users and CSV export for same users
- For Event Summary list requests (GET all), allow authenticated users to see both public events and any private events that those users otherwise have permission to see, instead of only public events

## [v1.4.7](https://github.com/USGS-WiM/whispersservices/releases/tag/v1.4.7) - 2020-02-07

### Changed

- Ensure both detail and summary Event serializers produce full nested organization objects, not just IDs

## [v1.4.6](https://github.com/USGS-WiM/whispersservices/releases/tag/v1.4.6) - 2020-02-07

### Changed

- Rename eventorganizations field on EventDetail serializers to just organizations, and add that field to all EventSummary serializers
- Upgrade dependencies

## [v1.4.5](https://github.com/USGS-WiM/whispersservices/releases/tag/v1.4.5) - 2020-01-27

### Fixed

- Fix bug in Event POST caused by user-submitted Undetermined EventDiagnosis

## [v1.4.4](https://github.com/USGS-WiM/whispersservices/releases/tag/v1.4.4) - 2020-01-23

### Changed

- Impose unique constraint on User email field

## [v1.4.3](https://github.com/USGS-WiM/whispersservices/releases/tag/v1.4.3) - 2020-01-19

### Changed

- Upgrade dependencies

## [v1.4.2](https://github.com/USGS-WiM/whispersservices/releases/tag/v1.4.2) - 2019-12-02

### Fixed

- Fix bug in Staff view caused by querying Comment model

## [v1.4.1](https://github.com/USGS-WiM/whispersservices/releases/tag/v1.4.1) - 2019-11-25

### Changed

- Update permissions for Comment, ServiceRequest, Staff, EventContact, EventLocationContact

## [v1.4.0](https://github.com/USGS-WiM/whispersservices/releases/tag/v1.4.0) - 2019-11-06

### Added

- Auto-generate a comment when service request response is updated

## [v1.3.12](https://github.com/USGS-WiM/whispersservices/releases/tag/v1.3.12) - 2019-11-01

### Changed

- Add high_impact field to Diagnosis model

## [v1.3.11](https://github.com/USGS-WiM/whispersservices/releases/tag/v1.3.11) - 2019-10-29

### Changed

- Include creator details of service requests in event details

## [v1.3.10](https://github.com/USGS-WiM/whispersservices/releases/tag/v1.3.10) - 2019-10-09

### Changed

- Exclude private events from EventGroup lists accessed by public

## [v1.3.9](https://github.com/USGS-WiM/whispersservices/releases/tag/v1.3.9) - 2019-10-04

### Changed

- Ensure 'Pending' is assigned as request_response to new ServiceRequests if a request_response value was not submitted, and not rely on the model to assign it as default, to prevent a database error when the 'Pending' record may not exist

## [v1.3.8](https://github.com/USGS-WiM/whispersservices/releases/tag/v1.3.8) - 2019-10-04

### Changed

- Ensure all validation error responses are JSON

## [v1.3.7](https://github.com/USGS-WiM/whispersservices/releases/tag/v1.3.7) - 2019-10-02

### Fixed

- Fix create permissions for non-admin roles on Comment model

## [v1.3.6](https://github.com/USGS-WiM/whispersservices/releases/tag/v1.3.6) - 2019-09-20

### Changed

- Make ServiceRequest response_type default to "Pending", and prevent the "Pending" record from ever appearing in ServiceRequestResponse GET requests

## [v1.3.5](https://github.com/USGS-WiM/whispersservices/releases/tag/v1.3.5) - 2019-09-18

### Changed

- Ensure EventDiagnosisSerializer suspect field defaults to True not False

## [v1.3.4](https://github.com/USGS-WiM/whispersservices/releases/tag/v1.3.4) - 2019-09-17

### Fixed

- Fix recently introduced bug in EventDiagnosis create for the situation when the suspect field is not submitted

## [v1.3.3](https://github.com/USGS-WiM/whispersservices/releases/tag/v1.3.3) - 2019-09-17

### Fixed

- Fix EventDetails combined_comments sorting bug

## [v1.3.2](https://github.com/USGS-WiM/whispersservices/releases/tag/v1.3.2) - 2019-09-17

### Changed

- Ensure Undetermined EventDiagnoses are removed in the case of a new Event being created with an EventDiagnosis and complete set to True

### Fixed

- Fix bug where some has_create_permission() methods did not have a return statement

## [v1.3.1](https://github.com/USGS-WiM/whispersservices/releases/tag/v1.3.1) - 2019-09-06

### Changed

- Order combined_comments objects descending by ID so newest appear first

## [v1.3.0](https://github.com/USGS-WiM/whispersservices/releases/tag/v1.3.0) - 2019-09-06

### Added

- Add new combined_comments field to EventDetails

## [v1.2.0](https://github.com/USGS-WiM/whispersservices/releases/tag/v1.2.0) - 2019-09-05

### Added

- Refactor permissions to eliminate vulnerabilities and remove bug that prevented creation of Event child objects by collaborators

## [v1.1.3](https://github.com/USGS-WiM/whispersservices/releases/tag/v1.1.3) - 2019-08-26

### Changed

- Ensure User role and org validation happens only on create
- Change User has_write_permission to return True to restore proper object permissions

## [v1.1.2](https://github.com/USGS-WiM/whispersservices/releases/tag/v1.1.2) - 2019-08-20

### Changed

- Ensure password is never saved unencrypted
- Ensure password validation happens on create as well as update

## [v1.1.1](https://github.com/USGS-WiM/whispersservices/releases/tag/v1.1.1) - 2019-08-15

### Changed

- Forbid anonymous users use of all unsafe methods except for a few exceptions (POST to auth, user, and the several request_new endpoints)

## [v1.1.0](https://github.com/USGS-WiM/whispersservices/releases/tag/v1.1.0) - 2019-08-15

### Added

- Implement new documentation based on openapi
- Update all dependencies

## [v1.0.4](https://github.com/USGS-WiM/whispersservices/releases/tag/v1.0.4) - 2019-07-31

### Fixed

- Fix bug in EventLocation doing unnecessary validations of minimum start date and species, which are already being validated in Event

## [v1.0.3](https://github.com/USGS-WiM/whispersservices/releases/tag/v1.0.3) - 2019-07-24

### Fixed

- Fix bug in SpeciesDiagnosis validation caused by checking a list item that may not exist

## [v1.0.2](https://github.com/USGS-WiM/whispersservices/releases/tag/v1.0.2) - 2019-07-23

### Changed

- Return Events in descending ID order (newest first)
- Move all remaining event chain serializer business rules into validation methods rather than create or update methods if not already there

### Fixed

- Fix bug in EventLocation and EventDiagnosis caused by full event chain create mis-check

## [v1.0.1](https://github.com/USGS-WiM/whispersservices/releases/tag/v1.0.1) - 2019-07-17

### Fixed

- Fix bug in validations to Event child objects when not in full event chain create

## [v1.0.0](https://github.com/USGS-WiM/whispersservices/releases/tag/v1.0.0) - 2019-07-15

### Added

- Ensure write_collaborators can update the objects shared with them
- Ensure Event Diagnoses can be created when an Event is created and simultaneously set to complete
