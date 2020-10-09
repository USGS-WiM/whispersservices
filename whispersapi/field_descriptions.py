class ModelFieldDescriptions:
    def __init__(self, field_name_list):
        for k, v in field_name_list.items():
            setattr(self, k, v)


event = ModelFieldDescriptions({
    'event_type': 'A foreign key integer value identifying a wildlife morbidity or mortality event',
    'event_reference': 'Name or number for an event designated by event owner',
    'complete': 'A boolean value indicating if an event is complete or incomplete. A complete event means it has ended, diagnostic tests are completed, and all information is updated in WHISPers',
    'start_date': 'The date this event started on',
    'end_date': 'The date this event ended on',
    'affected_count': 'An integer value for total number affected in this event',
    'staff': 'A foreign key integer value identifying a staff member',
    'event_status': 'A foreign key integer value identifying event statuses specific to NWHC.',
    'legal_status': 'A foreign key integer value identifying legal procedures associated with an event',
    'legal_number': 'An alphanumeric value of legal case identifier',
    'quality_check': 'The date an NWHC staff and event owner make changes and check the record',
    'public': 'A boolean value indicating if an event is public or not',
    'read_collaborators': 'A many to many releationship of read collaborators based on a foreign key integer value indentifying a user',
    'write_collaborators': 'A many to many releationship of write collaborators based on a foreign key integer value indentifying a user',
    'eventgroups': 'A foreign key integer identifying the user who last modified the object',
    'organizations': 'A many to many releationship of organizations based on a foreign key integer value indentifying an organization',
    'contacts': 'A many to many releationship of contacts based on a foreign key integer value indentifying a contact',
    'comments': 'A many to many releationship of comments based on a foreign key integer value indentifying a comment'
})