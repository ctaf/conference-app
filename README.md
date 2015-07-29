# Conference App

Conference App is a Google Cloud Endpoint API, which is able to serve as a
backend API for a variety of frontend clients: web (javascript) clients as well
as Android and iOS clients.
This project also provides a ready-to-use web frontend, a fully-fledged HTML
page with a javascript-based access to the backend API.
Among others, the API provides functionality for OAuth2-based user
authentication, user profiles as well as conference and session management.



## Setup

0. Make sure to fulfil the software requirements:
  - [Python 2.7][1]
  - [App Engine SDK for Python][2], version 1.7.5 or higher.

1. Clone this repo.

2. Create a project on the [Google Developer Console][3].

3. Fire up the dev-server locally:
  - via GoogleAppEngineLauncher.
  - via command line: `your-appengine-directory/dev_appserver.py
     your-project-directory`.

4. Update the value of `application` in `app.yaml` from `your-app-id`
   to the app ID you have registered in the Google Developer Console.

5. Deploy the app to GoogleAppEngine:
  - via GoogleAppEngineLauncher.
  - via command line: `your-appengine-directory/appcfg.py -A your-app-id
     update your-project-directory`.

6. Access the web frontend via the dev-server on `localhost:8080`.

7. Access the frontend on GoogleAppEngine via `your-app-id.appspot.com`.

8. Explore and enjoy :sunglasses:.



## Documentation


### Models

#### Session
Includes all data of a conference session and is designed with a parent
relation to the corresponding conference, which provides an easy way to retrieve
all sessions of a specific conference.
The `speakers` property is designed as a repeated field, as there might be more
than one speaker in some cases (e.g. at workshops). The property holds their
keys which makes a fast retrieval of the corresponding speaker objects
possible.
The `typeOfSession` property could be considered an enumerated type (typically, a
conference features a defined, limited set of session types), but this is
left to the corresponding frontends and thus is not directly implemented in the
backend API.
The `startTime` property is provided in 24-hour format which allows a time-based
ordering of the sessions, e.g. for a daily schedule.

- `name` -- Name or title of the session, required field on creation.

- `highlights` -- Some keywords or tags which provide a brief overview of the main
topics.

- `speakers` -- Name(s) of the speaker(s).

- `typeOfSession` -- Type of the session, e.g. lecture, talk or workshop.

- `date` -- Date of the session, supplied in the form `YYYY-MM-DD`.

- `startTime` -- Begin of the session, supplied in the form `hh:mm` (24-hour format).

- `duration` -- Duration of the session, given in minutes.


#### Speaker
A lightweight object model for session speakers with two properties. While a
simple string implementation using the speaker's name would be possible too,
the object-based design inherently provides uniqueness by the entitiy keys,
which simplifies searching for specific speakers, as well as their distinction
per se.

- `name` -- Name of the speaker.

- `email` -- Email contact of the speaker.

#### Profile
Holds all data from a registered user. Beside name, email address and a list of
conferences the user has registered for, the Profile object also keeps track of
the user's wishlist as a list of strings (consisting of websafeSessionKeys).

- `displayName` -- Name of the user.

- `mainEmail` -- Primary contact email of the user.

- `teeShirtSize` -- T-shirt size of the user. The following values are allowed:
  [XS_M XS_W S_M S_W M_M M_W L_M L_W XL_M XL_W XXL_M XXL_W XXXL_M XXXL_W]

- `sessionWishlist` -- A list containing the sessions the user is interested
  in (supplied as websafeSessionKeys).

- `conferenceKeysToAttend` -- A list of conferences the user has registered for
  (supplied as websafeConferenceKeys).


### Functionality

#### User Registration & Authentication
Users might register to the Conference App via their Google account, based on
the OAuth-2 protocol. Only registered users are allowed to modify content, i.e.
to create and update conferences and sessions, or to register for
conferences.

#### Conference Management
Conferences can be created and modified (by registered users) and provide
various information, such as start date, topics, speakers, available seats and
location. For every conference, one or more sessions can be created, featuring
highlights, speakers, a start time and a session type.
In addition to creating and modifying conferences, they can be queried by their
properties in various manners.

#### Announcements & Featured Speaker
Conferences that are nearly sold out (less than 6 seats available) are
regularly cached by a cron job (running every 1 hour) and an announcement is
created featuring these conferences, which is kept in memcache and available
via the API method `getAnnouncement`.
Also, whenever a new session is created, and the supplied speaker already
occurs in one or more other sessions within that conference, he or she becomes
the featured speaker, whose name is also held in memcache, available via
`getFeaturedSpeaker`.


### API Reference
The Conference App provides all its functionality in form of Endpoints APIs,
which can be called by all frontend clients. These Endpoints methods are also
used by the included Javascript web client.

#### addSessionToWishlist(SessionKey)
Add the specified session to the current user's wishlist.

#### createConference(ConferenceForm)
Create a new conference entity with the properties supplied in ConferenceForm.

#### createSession(SessionForm, websafeConferenceKey)
Create a new session for the given conference with the properties supplied in the SessionForm.

#### getAnnouncement()
Return the current announcement from memcache.

#### getConference(websafeConferenceKey)
Return the requested conference.

#### getConferenceSessions(websafeConferenceKey)
Return all sessions of the requested conference.

#### getConferenceSessionsByType(websafeConferenceKey, typeOfSession)
Return all sessions of a particular type (see typeOfSession property) for the requested conference.

#### getConferenceSpeakers(websafeConferenceKey)
Return all speakers for the requested conference (see section _Additional queries_ for details).

#### getConferencesCreated()
Return all conferences created by the current user.

#### getConferencesToAttend()
Return all conferences the current user has registered for.

#### getFeaturedSpeaker(websafeConferenceKey)
Return the featured speaker for the given conference.

#### getNonWorkshops()
Return all non-workshop sessions starting before 7pm (see section _Query-related problem_ for details).

#### getProfile()
Return the current user's profile data.

#### getSessionsBySpeaker(websafeSpeakerKey)
Return all sessions given by a particular speaker, across all conferences.

#### getSessionsInWishlist()
Returns all sessions on the current user's wishlist.

#### getUpcomingConferences()
Return all upcoming conferences (held this and the next month). See section _Additional queries_ for details.

#### queryConferences(ConferenceQueryForm)
Query for conferences, using the filters supplied by the ConferenceQueryForm.

#### registerForConference(websafeConferenceKey)
Register the current user for the given conference.

#### saveProfile(ProfileMiniForm)
Update the current user's profile with the information provided in the ProfileMiniForm.

#### unregisterFromConference(websafeConferenceKey)
Unregister the current user from the given conference.

#### updateConference(ConferenceForm, websafeConferenceKey)
Update the given conference, using the properties supplied in the ConferenceForm.



## Problems

### Additional queries

#### List all speakers of a conference.
Allows to deliver all speakers at a glance: Will I be able to see and meet
interesting speakers at the conference? Will there be well-known speakers of
high relevance in my field?
Provided by the API method `getConferenceSpeakers`.

#### View upcoming conferences.
See all conferences taking place in the current and the next month: Are there
any interesting conferences which have not attracted my attention so far? Might
there even be an available seat for them? Generally, are there any conferences
currently taking place on topics I am interested in?
Provided by the API method `GetUpcomingConferences`.

### Query-related problem
The Datastore API does not support inequality filtering on more than one
property. Instead, filtering for both the session type and the start time has
to be done in two steps.
First, two separate queries are performed, one for all non-workshop sessions
and one for all sessions starting before 7pm. Second, the results of these two
queries are further processed by the backend to yield those entities occuring
in both queries.
An efficient way to achieve this filtering in Python is to use set operations,
as exemplified in `getNonWorkshops`:
```python
non_workshop = Session.query(Session.typeOfSession != 'workshop')
before_seven = Session.query(Session.startTime <= time(19, 0))
intersect = set([n.key.urlsafe() for n in non_workshop]
            ) & set([b.key.urlsafe() for b in before_seven])
```

Note that Python sets require hashable types, therefore the string
representation of the entity keys is used here.



## Creator

**Philip Taferner**

* [Google+](https://plus.google.com/u/0/+PhilipTaferner/posts)
* [Github](https://github.com/ctaf)

[1]: https://www.python.org/download/releases/2.7
[2]: https://developers.google.com/appengine
[3]: https://console.developers.google.com
