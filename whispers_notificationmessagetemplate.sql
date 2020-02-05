INSERT INTO "whispers_notificationmessagetemplate"("id", "created_date", "modified_date", "name", "message_variables", "created_by_id", "modified_by_id", "body_template", "subject_template") VALUES (6, '2019-11-26', '2020-01-19', 'Collaborator Added', '{first_name,last_name,username,collaborator_type,event_id}', 1, 1, '<p><strong>You have been added as a {collaborator_type} collaborator for WHISPers event {event_id} by {first_name} {last_name} ({username}).</strong></p>
<p>Follow the event link provided to access privileged event information (event details), remove yourself from the event ("Collaborators" section on event details), and manage event update notifications (dashboard).</p>', 'Collaborator Access: Event {event_id}');
INSERT INTO "whispers_notificationmessagetemplate"("id", "created_date", "modified_date", "name", "message_variables", "created_by_id", "modified_by_id", "body_template", "subject_template") VALUES (1, '2019-11-26', '2020-01-19', 'High Impact Diseases', '{species_diagnosis,event_id,event_location}', 1, 1, '<p><strong>A high impact disease - {species_diagnosis} - has been added to Event {event_id} in {event_location}.</strong></p>
<p>Please review and determine if any action is required.</p>', 'High Impact Disease: {species_diagnosis} in {event_location}');
INSERT INTO "whispers_notificationmessagetemplate"("id", "created_date", "modified_date", "name", "message_variables", "created_by_id", "modified_by_id", "body_template", "subject_template") VALUES (2, '2019-11-26', '2020-01-19', 'User Change Request', '{first_name,last_name,username,current_role,new_role,current_organization,new_organization,comment}', 1, 1, '<p>The user {first_name} {last_name} ({username}) has requested an account role change to {new_role}.</p>
<p>Organization: {new_organization}</p>
<p>Comment: {comment}</p>', 'User Account Change Request: {new_organization}');
INSERT INTO "whispers_notificationmessagetemplate"("id", "created_date", "modified_date", "name", "message_variables", "created_by_id", "modified_by_id", "body_template", "subject_template") VALUES (4, '2019-11-26', '2020-01-19', 'New Lookup Item Request', '{first_name,last_name,email,organization,lookup_table,lookup_item}', 1, 1, '<p>A user {first_name} {last_name} ({email}) from {organization} has requested a new {lookup_table} lookup item be added.</p>
<p>Comment: {lookup_item}</p>', 'New Lookup Request: {lookup_table}');
INSERT INTO "whispers_notificationmessagetemplate"("id", "created_date", "modified_date", "name", "message_variables", "created_by_id", "modified_by_id", "body_template", "subject_template") VALUES (5, '2019-11-26', '2020-01-19', 'Collaboration Request', '{first_name,last_name,organization,event_id,comment,email}', 1, 1, '<p><strong>WHISPers user {first_name} {last_name} from {organization} has requested to collaborate on event {event_id}.</strong></p>
<p>Additional details (if provided by requester) are as follows: {comment}.</p>
<p>You can choose whether or not to add the collaborator, and the level of access to grant to the event (read only or read and write). If you choose not to add the user to this event, no action is required. If you would like to add this user as a collaborator, click on the event link and enter the user email address {email} in the "Collaborators" section on the event details page.</p>', 'Collaborator Request: Event {event_id}');
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
INSERT INTO "whispers_notificationmessagetemplate"("id", "created_date", "modified_date", "name", "message_variables", "created_by_id", "modified_by_id", "body_template", "subject_template") VALUES (14, '2020-01-31', '2020-01-31', 'Collaboration Events', '{first_name,last_name,created_updated,event_id,event_date,updates,new_updated}', 1, 1, '<p><strong>User {first_name} {last_name} has {created_updated} WHISPers Event {event_id}, on which you are a collaborator, on {event_date}.</strong></p>
<p>Updates were made to the following sections (if applicable): {updates}</p>
<p>You received this message because your WHISPers notifications are set for {new_updates} WHISPers Events for which you are the event owner. Notification settings can be changed on your WHISPers dashboard.</p>', '"Your Collaboration Events" Notification: Event {event_id}');
INSERT INTO "whispers_notificationmessagetemplate"("id", "created_date", "modified_date", "name", "message_variables", "created_by_id", "modified_by_id", "body_template", "subject_template") VALUES (15, '2020-02-04', '2020-02-04', 'Stale Events', '{event_id,event_location,event_date,stale_period}', 1, 1, '<p><strong>Update Needed</strong>: You are the event owner for WHISPers Event {event_id} in {event_location} created on {event_date}. You are receiving this auto-notification because the event has been inactive for {stale_period}.</p>
<p>Please log in, review the event, and update any missing or outdated information, including total number sick and dead, final event diagnosis, and ending date. Toggle the WHISPers Record Status to "Complete" if no further updates are anticipated.</p>
<p>For more details about how to complete an event, see the user guides and metadata at <a href="https://www.usgs.gov/nwhc/whispers ">https://www.usgs.gov/nwhc/whispers</a></p>
<p>If the event remains inactive for over 90 days, the status will be automatically switched to "Complete". (You can always toggle it back to "Incomplete" if further edits are needed).</p>
<p><strong>Thank you for helping provide better situational awareness for the wildlife management community.</strong></p>', 'Update Needed: Event {event_id}');
INSERT INTO "whispers_notificationmessagetemplate"("id", "created_date", "modified_date", "name", "message_variables", "created_by_id", "modified_by_id", "body_template", "subject_template") VALUES (13, '2020-01-31', '2020-01-31', 'Organization Events', '{first_name,last_name,created_updated,event_id,event_date,updates,new_updated}', 1, 1, '<p><strong>User {first_name} {last_name} has {created_updated} your organization''s WHISPers Event {event_id} on event_date.</strong></p>
<p>Updates were made to the following sections (if applicable): {updates}</p>
<p>You received this message because your WHISPers notifications are set for {new_updated} WHISPers Events which are owned by your organization. Notification settings can be changed on your WHISPers dashboard.</p>', '"Your Organization Events" Notification: Event {event_id}');
INSERT INTO "whispers_notificationmessagetemplate"("id", "created_date", "modified_date", "name", "message_variables", "created_by_id", "modified_by_id", "body_template", "subject_template") VALUES (12, '2020-01-31', '2020-01-31', 'Your Events', '{first_name,last_name,created_updated,event_id,event_date,updates,new_updated}', 1, 1, '<p><strong>User {first_name} {last_name} has {created_updated} WHISPers Event {event_id}, on which you are a collaborator, on {event_date}.</strong></p>
<p>Updates were made to the following sections (if applicable): {updates}</p>
<p>You received this message because your WHISPers notifications are set for {new_updated} WHISPers Events for which you are the event owner. Notification settings can be changed on your WHISPers dashboard.</p>', '"Your Events" Notification: Event {event_id}');
INSERT INTO "whispers_notificationmessagetemplate"("id", "created_date", "modified_date", "name", "message_variables", "created_by_id", "modified_by_id", "body_template", "subject_template") VALUES (11, '2020-01-30', '2020-01-30', 'ALL Events', '{event_id,organiation,event_location,event_date,new_updated,created_updated,updates}', 1, 1, '<p><strong>WHISPers Event {event_id} in {event_location} was {created_updated} on {event_date} by {organization}.</strong></p>
<p>Updates were made to the following sections (if applicable):{updates}</p>
<p>You received this message because your WHISPers notifications are set for All {new_updated} WHISPers Events. Notification settings can be changed on your WHISPers dashboard.</p>', '"All Events" Notification: Event {event_id}');
INSERT INTO "whispers_notificationmessagetemplate"("id", "created_date", "modified_date", "name", "message_variables", "created_by_id", "modified_by_id", "body_template", "subject_template") VALUES (16, '2020-02-04', '2020-02-04', 'Quality Check', '{event_id}', 1, 1, '<p>Quality Check needed for WHISPers Event {event_id}.</p>', 'Quality Check: Event {event_id}');
INSERT INTO "whispers_notificationmessagetemplate"("id", "created_date", "modified_date", "name", "message_variables", "created_by_id", "modified_by_id", "body_template", "subject_template") VALUES (3, '2019-11-26', '2020-01-19', 'User Change Request Response Yes', '{role,organization}', 1, 1, '<h2>You''ve been assigned the role of {role} within {organization}.</h2>
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
<td>Partner User</td>
<td>can submit data, edit self-created data, and view non-public data within own organization.</td>
</tr>
<tr>
<td>Partner Manager</td>
<td>anything a "user" can do, plus can edit any data within own organization.</td>
</tr>
<tr>
<td>Partner Administrator</td>
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
INSERT INTO "whispers_notificationmessagetemplate"("id", "created_date", "modified_date", "name", "message_variables", "created_by_id", "modified_by_id", "body_template", "subject_template") VALUES (17, '2020-02-05', '2020-02-05', 'User Change Request Response No', '{}', 1, 1, '<div>Thank you very much for your interest in the Wildlife Health Information Sharing Partnership (WHISPers). Currently, users from state, federal, and tribal natural resources agencies with management authority over species and/or land are being enrolled as WHISPers Partners.</div>
<br /><br />
<div>Based on the information provided, you have been assigned the role of <strong>Public User</strong>. You have access to all publicly-available historical and current WHISPers event information and can now log in with your username and password and save your searches of event data to your user dashboard.</div>
<br /><br />
<div>Wildlife professionals involved in collaborative projects with state, federal, or tribal natural resource management agencies can be sponsored for enrollment as a WHISPers "Affiliate," which allows the WHISPers partner to grant access to detailed information for specific events. If you''d like to be an Affiliate, please talk with your collaborating partner then email <a href="mailto:whispers@usgs.gov">whispers@usgs.gov</a> with the name and agency of the state, federal, or tribal sponsor(s) you have been in contact with regarding being designated an Affiliate user. See the USGS Wildlife Health Center website for more information about roles, as well as to find user guides and metadata (<a href="https://www.usgs.gov/nwhc/whispers">https://www.usgs.gov/nwhc/whispers</a>).</div>
<br /><br />
<div>Thanks again!</div>', 'User Account Assigned');
INSERT INTO "whispers_notificationmessagetemplate"("id", "created_date", "modified_date", "name", "message_variables", "created_by_id", "modified_by_id", "body_template", "subject_template") VALUES (18, '2020-02-05', '2020-02-05', 'User Created', '{}', 1, 1, '<p>Thank you very much for your interest in the Wildlife Health Information Sharing Partnership event reporting system (WHISPers). <strong>You can now log in with your username and password and save your searches of event data to your user dashboard.</strong></p>
<p>See the USGS National Wildlife Health Center website for user guides and metadata (<a href="https://www.usgs.gov/centers/nwhc/science/whispers">https://www.usgs.gov/centers/nwhc/science/whispers</a>).</p>
<p>For any questions, please contact <a href="mailto:whispers@usgs.gov">whispers@usgs.gov</a></p>
<p>Thanks again!</p>', 'User Account Assigned');
INSERT INTO "whispers_notificationmessagetemplate"("id", "created_date", "modified_date", "name", "message_variables", "created_by_id", "modified_by_id", "body_template", "subject_template") VALUES (20, '2020-02-05', '2020-02-05', 'User Change Request Pending', '{}', 1, 1, '<p><strong>Your request for a WHISPers account has been received; we will be back in touch as soon as possible.</strong></p>
<p>Thank you very much for your interest in the Wildlife Health Information Sharing Partnership event reporting system (WHISPers). WHISPers is in the early roll out phase and we are working hard to properly integrate various natural resource management agencies into the system. We are reaching out to our wildlife health contacts in your area to ensure we structure your organization and individual user roles correctly.</p>
<p>If you have an urgent wildlife disease situation requiring immediate diagnostic assistance or field response consultation, please contact the USGS National Wildlife Health Center at 608-270-2480 or Hawaii Field Station at 808-792-9520.</p>
<p>Thanks again!</p>', 'User Account Request Received  ');
INSERT INTO "whispers_notificationmessagetemplate"("id", "created_date", "modified_date", "name", "message_variables", "created_by_id", "modified_by_id", "body_template", "subject_template") VALUES (19, '2020-02-05', '2020-02-05', 'Custom Notification', '{new_updated,field,criteria,organization,created_updated,event_id,event_date,updates}', 1, 1, '<p>Your Custom Notifications are set for {new_updated} Events with {field}: {criteria}.</p>
<p><strong>{organization} has {created_updated} WHISPers Event {event_id} on {event_date}.</strong></p>
<p>Updates were made to the following sections (if applicable): {updates}</p>
<p>Notification settings can be changed on your WHISPers dashboard.</p>', 'Custom Notification: Event {event_id}');
