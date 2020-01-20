INSERT INTO "whispers_notificationmessagetemplate"("id", "created_date", "modified_date", "name", "message_variables", "created_by_id", "modified_by_id", "body_template", "subject_template") VALUES (1, '2019-11-26', '2020-01-19', 'High Impact Diseases', '{species_diagnosis,event_id,event_location}', 1, 1, '<p><strong>A high impact disease - {species_diagnosis} - has been added to Event {event_id} in {event_location}.</strong></p>
<p>Please review and determine if any action is required.</p>', 'High Impact Disease: {species_diagnosis} in {event_location}');
INSERT INTO "whispers_notificationmessagetemplate"("id", "created_date", "modified_date", "name", "message_variables", "created_by_id", "modified_by_id", "body_template", "subject_template") VALUES (2, '2019-11-26', '2020-01-19', 'User Change Request', '{first_name,last_name,username,current_role,new_role,current_organization,new_organization,comment}', 1, 1, '<p>The user {first_name} {last_name} ({username}) has requested an account role change to {new_role}.</p>
<p>Organization: {new_organization}</p>
<p>Comment: {comment}</p>', 'User Account Change Request: {new_organization}');
INSERT INTO "whispers_notificationmessagetemplate"("id", "created_date", "modified_date", "name", "message_variables", "created_by_id", "modified_by_id", "body_template", "subject_template") VALUES (3, '2019-11-26', '2020-01-19', 'User Change Request Response', '{role,organization}', 1, 1, '<h2>You''ve been assigned the role of {role} within {organization}.</h2>
<p>Thank you very much for your interest in the Wildlife Health Information Sharing Partnership event reporting system (WHISPers). You can now log in with your username and password to access the features available to your role.</p>
<p>In short, the roles are:</p>
<table>
<thead>
<tr>
<td>Role</td>
<td>Description</td>
</tr>
</thead>
<tbody>
<tr>
<td>User</td>
<td>can submit data, edit self-created data, and view non-public data within own organization.</td>
</tr>
<tr>
<td>Manager</td>
<td>anything a "user" can do, plus can edit any data within own organization.</td>
</tr>
<tr>
<td>Administrator</td>
<td>anything a "manager" can do, plus can validate and delete users and user info within own organization.</td>
</tr>
<tr>
<td>Affiliate</td>
<td>can be invited by a user, manager, or administrator to collaborate on an event.</td>
</tr>
</tbody>
</table>
<p>See the USGS National Wildlife Health Center website for more information about roles, as well as to find user guides and metadata (<a href="https://www.usgs.gov/nwhc/whispers">https://www.usgs.gov/nwhc/whispers</a>).</p>
<p>If you would like help entering a wildlife health event into WHISPers and/or use WHISPers to facilitate submission of carcasses to the USGS National Wildlife Health Center, please contact the epidemiologist on duty at <a href="mailto:NWHC-epi@usgs.gov">NWHC-epi@usgs.gov</a> or (608) 270-2480 and they can guide you through the process.</p>
<p>For any technical questions about the WHISPers website, please contact <a href="mailto:whispers@usgs.gov">whispers@usgs.gov</a>.</p>
<p><strong>Thanks again, and welcome to the WHISPers community!</strong></p>', 'User Account Assigned');
INSERT INTO "whispers_notificationmessagetemplate"("id", "created_date", "modified_date", "name", "message_variables", "created_by_id", "modified_by_id", "body_template", "subject_template") VALUES (4, '2019-11-26', '2020-01-19', 'New Lookup Item Request', '{first_name,last_name,email,organization,lookup_table,lookup_item}', 1, 1, '<p>A user {first_name} {last_name} ({email}) from {organization} has requested a new {lookup_table} lookup item be added.</p>
<p>Comment: {lookup_item}</p>', 'New Lookup Request: {lookup_table}');
INSERT INTO "whispers_notificationmessagetemplate"("id", "created_date", "modified_date", "name", "message_variables", "created_by_id", "modified_by_id", "body_template", "subject_template") VALUES (5, '2019-11-26', '2020-01-19', 'Collaboration Request', '{first_name,last_name,organization,event_id,comment,email}', 1, 1, '<p><strong>WHISPers user {first_name} {last_name} from {organization} has requested to collaborate on event {event_id}.</strong></p>
<p>Additional details (if provided by requester) are as follows: {comment}.</p>
<p>You can choose whether or not to add the collaborator, and the level of access to grant to the event (read only or read and write). If you choose not to add the user to this event, no action is required. If you would like to add this user as a collaborator, click on the event link and enter the user email address {email} in the "Collaborators" section on the event details page.</p>', 'Collaborator Request: Event {event_id}');
INSERT INTO "whispers_notificationmessagetemplate"("id", "created_date", "modified_date", "name", "message_variables", "created_by_id", "modified_by_id", "body_template", "subject_template") VALUES (6, '2019-11-26', '2020-01-19', 'Collaborator Added', '{first_name,last_name,username,collaborator_type,event_id}', 1, 1, '<p><strong>You have been added as a {collaborator_type} collaborator for WHISPers event {event_id} by {first_name} {last_name} ({username}).</strong></p>
<p>Follow the event link provided to access privileged event information (event details), remove yourself from the event ("Collaborators" section on event details), and manage event update notifications (dashboard).</p>', 'Collaborator Access: Event {event_id}');
INSERT INTO "whispers_notificationmessagetemplate"("id", "created_date", "modified_date", "name", "message_variables", "created_by_id", "modified_by_id", "body_template", "subject_template") VALUES (7, '2019-11-26', '2020-01-19', 'Alert Collaborator', '{first_name,last_name,organization,event_id,comment,recipients}', 1, 1, '<p><strong>User {first_name} {last_name} ({organization}) has created a Collaborator Alert for WHISPers Event {event_id}.</strong></p>
<p>Details (if provided): {comment}.</p>
<p>Alert sent to: {recipients}.</p>
<p><strong>Note</strong>: To help ensure timeliness of important communications, Collaborator Alerts override your other WHISPers email notification settings. If you would like to not receive any further alerts about this event, best to remove yourself from the "Collaborators" section on the event details page.</p>', 'Collaborator Alert: Event {event_id}');
INSERT INTO "whispers_notificationmessagetemplate"("id", "created_date", "modified_date", "name", "message_variables", "created_by_id", "modified_by_id", "body_template", "subject_template") VALUES (8, '2019-11-26', '2020-01-19', 'Service Request', '{first_name,last_name,organization,service_request,event_id,event_location,comment}', 1, 1, '<p>User {first_name} {last_name} with organization {organization} has requested {service_request} services for event {event_id} in {event_location}.</p>
<p>Comments: {comment}</p>', '{service_request} Request: Event {event_id}');
INSERT INTO "whispers_notificationmessagetemplate"("id", "created_date", "modified_date", "name", "message_variables", "created_by_id", "modified_by_id", "body_template", "subject_template") VALUES (9, '2019-11-26', '2020-01-19', 'Service Request Response', '{event_id}', 1, 1, '<p><strong>A response to a diagnostic or consultative service request has been added to WHISPers Event {event_id}. Please go to the "Service Requests" section on the event page to review.</strong></p>
<p>If immediate assistance is required, please contact the USGS National Wildlife Health Center Epidemiology Team at 608-270-2480 or the Hawaii Field Station at 808-792-9520.</p>', 'NWHC Services Response: Event {event_id}');
INSERT INTO "whispers_notificationmessagetemplate"("id", "created_date", "modified_date", "name", "message_variables", "created_by_id", "modified_by_id", "body_template", "subject_template") VALUES (10, '2019-11-26', '2020-01-19', 'Service Request Comment', '{event_id}', 1, 1, '<p><strong>A comment related to a diagnostic or consultative service request has been added to WHISPers Event {event_id}. Please go to the "Service Requests" section on the event page to review.</p>
<p>If a reply is needed, add a comment in the "Service Requests" section.</strong></p>
<p>If immediate assistance is required, please contact the USGS National Wildlife Health Center Epidemiology Team at 608-270-2480 or the Hawaii Field Station at 808-792-9520.</p>', 'NWHC Services Comment: Event {event_id}');
