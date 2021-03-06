VPATH=data


.INTERMEDIATE : %-amendment-with-data-year.csv \
	%-amendment-with-valid-start-dates.csv %-amendment-salary-summed.csv \
	%-amendment-no-salary-omitted.csv group-%.csv

%-amendment.csv : %-amendment-no-salary-omitted.csv
	# Rename fields.
	(echo employer,last_name,first_name,title,department,base_salary,extra_pay,date_started,id,responding_agency,data_year,salary; \
	tail -n +2 $<) > $@

%-amendment-no-salary-omitted.csv : %-amendment-salary-summed.csv
	# Remove records where no salary was reported.
	csvgrep -c total_pay -r '^$$' -i $< > $@;
	echo "Removed $$(csvgrep -c total_pay -r '^$$' $< | wc -l | xargs) records without salary"

%-amendment-salary-summed.csv : %-amendment-with-valid-start-dates.csv
	# Sum base pay and extra salary.
	cat $< | python data/processors/sum_salary.py > $@

%-amendment-with-valid-start-dates.csv : %-amendment-with-data-year.csv
	# Remove invalid dates.
	cat $< | python data/processors/validate_dates.py > $@

%-amendment-with-data-year.csv : %-amendment-with-agencies.csv
	# Add required data year field.
	perl -pe 's/$$/,2017/' $< > $@

.SECONDEXPANSION :
%-amendment-with-agencies.csv : $$(wildcard data/raw/$$*-amendment.csv $$*.csv) raw/foia-source-lookup.csv
	# Join standard data with agency lookup.
	csvjoin -c id,ID -e IBM852 $^ > $@

group-%.csv : raw/amendments-%
	# Combine a group of amended files. Remove all-null lines, i.e., those
	# starting with a comma. All rows should end with the id of the responding
	# agency. Remove stray, trailing empty fields.
	csvstack $</* | \
	grep -E '^,' -v | \
	perl -pe 's/,+$$//' > $@
