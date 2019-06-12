
-- ----------------------------
-- View structure for species_diag_orgs
-- ----------------------------
DROP VIEW IF EXISTS "public"."species_diag_orgs";
CREATE VIEW "public"."species_diag_orgs" AS  SELECT spdorg.species_diagnosis_id,
    string_agg((( SELECT org.name
           FROM whispers_organization org
          WHERE (org.id = spdorg.organization_id)))::text, ','::text) AS orgs
   FROM whispers_speciesdiagnosisorganization spdorg
  GROUP BY spdorg.species_diagnosis_id;

-- ----------------------------
-- View structure for event_orgs
-- ----------------------------
DROP VIEW IF EXISTS "public"."event_orgs";
CREATE VIEW "public"."event_orgs" AS  SELECT evorg.event_id,
    string_agg((( SELECT org.name
           FROM whispers_organization org
          WHERE (org.id = evorg.organization_id)))::text, ', '::text) AS orgs
   FROM whispers_eventorganization evorg
  GROUP BY evorg.event_id;

-- ----------------------------
-- View structure for event_diags
-- ----------------------------
DROP VIEW IF EXISTS "public"."event_diags";
CREATE VIEW "public"."event_diags" AS  SELECT evdiag.event_id,
    string_agg(( SELECT ((diag.name)::text ||
                CASE evdiag.suspect
                    WHEN true THEN ' suspect'::text
                    ELSE ''::text
                END)
           FROM whispers_diagnosis diag
          WHERE (diag.id = evdiag.diagnosis_id)), ', '::text) AS diags
   FROM whispers_eventdiagnosis evdiag
  GROUP BY evdiag.event_id;

-- ----------------------------
-- View structure for flat_event_details
-- ----------------------------
DROP VIEW IF EXISTS "public"."flat_event_details";
CREATE VIEW "public"."flat_event_details" AS  SELECT e.id AS event_id,
    e.created_by_id AS created_by,
    e.event_reference,
    ( SELECT et.name
           FROM whispers_eventtype et
          WHERE (et.id = e.event_type_id)) AS event_type,
        CASE e.complete
            WHEN true THEN 'Complete'::text
            ELSE 'Incomplete'::text
        END AS complete,
    ( SELECT event_orgs.orgs
           FROM event_orgs
          WHERE (event_orgs.event_id = e.id)) AS organization,
    e.start_date,
    e.end_date,
    e.affected_count,
    COALESCE(( SELECT event_diags.diags
           FROM event_diags
          WHERE (event_diags.event_id = e.id)), 'Undetermined'::text) AS event_diagnosis,
    el.id AS location_id,
    el.priority AS location_priority,
    ( SELECT al2.name
           FROM whispers_administrativeleveltwo al2
          WHERE (al2.id = el.administrative_level_two_id)) AS county,
    ( SELECT al1.name
           FROM whispers_administrativelevelone al1
          WHERE (al1.id = el.administrative_level_one_id)) AS state,
    ( SELECT c.name
           FROM whispers_country c
          WHERE (c.id = el.country_id)) AS country,
    el.start_date AS location_start,
    el.end_date AS location_end,
    ls.id AS location_species_id,
    ls.priority AS species_priority,
    ( SELECT s.name
           FROM whispers_species s
          WHERE (s.id = ls.species_id)) AS species_name,
    ls.population_count AS population,
    ls.sick_count AS sick,
    ls.dead_count AS dead,
    ls.sick_count_estimated AS estimated_sick,
    ls.dead_count_estimated AS estimated_dead,
        CASE ls.captive
            WHEN true THEN 'captive >72 hours'::text
            ELSE 'wild and/or free-ranging'::text
        END AS captive,
    ( SELECT ab.name
           FROM whispers_agebias ab
          WHERE (ab.id = ls.age_bias_id)) AS age_bias,
    ( SELECT sb.name
           FROM whispers_sexbias sb
          WHERE (sb.id = ls.sex_bias_id)) AS sex_bias,
    sd.id AS species_diagnosis_id,
    sd.priority AS species_diagnosis_priority,
    ((( SELECT d.name
           FROM whispers_diagnosis d
          WHERE (d.id = sd.diagnosis_id)))::text ||
        CASE sd.suspect
            WHEN true THEN ' suspect'::text
            ELSE ''::text
        END) AS speciesdx,
        CASE sd.cause_id
            WHEN NULL::integer THEN ''::text
            ELSE (
            CASE sd.suspect
                WHEN true THEN 'Suspect '::text
                ELSE ''::text
            END || (( SELECT dc.name
               FROM whispers_diagnosiscause dc
              WHERE (dc.id = sd.cause_id)))::text)
        END AS causal,
    sd.suspect,
    sd.tested_count AS number_tested,
    sd.positive_count AS number_positive,
    ( SELECT species_diag_orgs.orgs
           FROM species_diag_orgs
          WHERE (species_diag_orgs.species_diagnosis_id = sd.id)) AS lab,
    row_number() OVER () AS row_num
   FROM (((whispers_event e
     LEFT JOIN whispers_eventlocation el ON ((e.id = el.event_id)))
     LEFT JOIN whispers_locationspecies ls ON ((el.id = ls.event_location_id)))
     LEFT JOIN whispers_speciesdiagnosis sd ON ((ls.id = sd.location_species_id)));
