## Task 4: Indexes and queries
### Additional queries
#### List all speakers of a conference.
Allows to deliver all speakers at a glance: Will I be able to see and meet
interesting speakers at the conference? Will there be well-known speakers of
high relevance in my field?
Provided by the Endpoints method getConferenceSpeakers().

#### View upcoming conferences.
See all conferences taking place in the current and the next month: Are there
any interesting conferences which have not attracted my attention so far? Might
there even be an available seat for them? Generally, are there any conferences
currently taking place on topics I am interested in?
Provided by the Endpoints method GetUpcomingConferences.

### Query-related problem
The Datastore API does not support inequality filtering on more than one
property. Instead, filtering for both the session type and the start time has
to be done in two steps.
First, two separate queries are performed, one for all non-workshop sessions
and one for all sessions starting before 7pm. Second, the results of these two
queries are further processed by the backend to yield those entities occuring
in both queries.
An efficient way to achieve this filtering in Python is to use set operations,
as exemplified in getNonWorkshops():
```python
non_workshop = Session.query(Session.typeOfSession != 'workshop')
before_seven = Session.query(Session.startTime <= time(19, 0))
intersect = set([n.key.urlsafe() for n in non_workshop]
            ) & set([b.key.urlsafe() for b in before_seven])
```

Note that Python sets require hashable types, therefore the string
representation of the entity keys is used here.
