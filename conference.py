import datetime
import endpoints

from protorpc import remote
from protorpc import message_types

from google.appengine.api import memcache
from google.appengine.api import taskqueue
from google.appengine.ext import ndb

from models import ConflictException
from models import Profile
from models import ProfileMiniForm
from models import ProfileForm
from models import StringMessage
from models import MultiStringMessage
from models import BooleanMessage
from models import Session
from models import SessionForm
from models import SessionForms
from models import Conference
from models import ConferenceForm
from models import ConferenceForms
from models import ConferenceQueryForms
from models import Speaker
from models import TeeShirtSize

from settings import WEB_CLIENT_ID
from settings import ANDROID_CLIENT_ID
from settings import IOS_CLIENT_ID
from settings import ANDROID_AUDIENCE
from settings import EMAIL_SCOPE
from settings import API_EXPLORER_CLIENT_ID
from settings import MEMCACHE_ANNOUNCEMENTS_KEY
from settings import ANNOUNCEMENT_TPL
from settings import DEFAULTS
from settings import OPERATORS
from settings import FIELDS

from requests import CONF_GET_REQUEST
from requests import CONF_POST_REQUEST
from requests import TYPE_GET_REQUEST
from requests import WISH_POST_REQUEST
from requests import SESS_GET_REQUEST
from requests import SESS_POST_REQUEST

from utils import getUserId
from utils import validateUser


@endpoints.api(name='conference', version='v1', audiences=[ANDROID_AUDIENCE],
               allowed_client_ids=[WEB_CLIENT_ID, API_EXPLORER_CLIENT_ID,
               ANDROID_CLIENT_ID, IOS_CLIENT_ID], scopes=[EMAIL_SCOPE])
class ConferenceApi(remote.Service):
    """Conference API v0.5"""

# - - - Helper methods - - - - - - - - - - - - - - - - -

    def _checkConf(self, conf):
        if not conf:
            raise endpoints.NotFoundException('No conference found.')


    def _validateOwner(self, wbsk, user_id):
        conf = ndb.Key(urlsafe=wbsk).get()
        self._checkConf(conf)

        # check that user is owner
        if user_id != conf.organizerUserId:
            raise endpoints.ForbiddenException(
                'Only the owner can update the conference.')


    def _addSpeakers(self, request, speakers):
        keys = []
        all_speakers = {sp.name: sp for sp in Speaker.query()}

        # Check if the speakers are already in the Datastore.
        for name in speakers:
            known_speaker = all_speakers.get(name)

            # And add them if necessary.
            if not known_speaker:
                s_key = Speaker(name=name).put().urlsafe()
                keys.append(s_key)

            else:
                s_key = known_speaker.key.urlsafe()
                keys.append(s_key)

                # Add speaker as featured speaker to memcache, if there
                # is at least one other session by this speaker at this
                # conference.
                if Session.query(Session.speakers.IN([s_key])):
                    cache_entry = '%s|%s' % (known_speaker.name,
                                             getattr(request, 'name'))
                    memcache.set(request.websafeConferenceKey,
                                 cache_entry)
        return keys


    def _getQuery(self, request):
        """Return formatted query from the submitted filters."""
        q = Conference.query()
        inequality_filter, filters = self._formatFilters(request.filters)

        # If exists, sort on inequality filter first.
        if not inequality_filter:
            q = q.order(Conference.name)
        else:
            q = q.order(ndb.GenericProperty(inequality_filter))
            q = q.order(Conference.name)

        for filtr in filters:
            if filtr["field"] in ["month", "maxAttendees"]:
                filtr["value"] = int(filtr["value"])

            formatted_query = ndb.query.FilterNode(
                filtr["field"], filtr["operator"], filtr["value"])
            q = q.filter(formatted_query)

        return q


    def _formatFilters(self, filters):
        """Parse, check validity and format user supplied filters."""
        formatted_filters = []
        inequality_field = None

        for f in filters:
            filtr = {field.name: getattr(f, field.name)
                     for field in f.all_fields()}

            try:
                filtr["field"] = FIELDS[filtr["field"]]
                filtr["operator"] = OPERATORS[filtr["operator"]]
            except KeyError:
                raise endpoints.BadRequestException(
                    "Filter contains invalid field or operator.")

            # Every operation except "=" is an inequality.
            if filtr["operator"] != "=":
                # Check if inequality operation has been used in previous
                # filters. Disallow the filter if inequality was performed on a
                # different field before. Track the field on which the
                # inequality operation is performed.
                if inequality_field and inequality_field != filtr["field"]:
                    raise endpoints.BadRequestException(
                        "Inequality filter is allowed on only one field.")
                else:
                    inequality_field = filtr["field"]

            formatted_filters.append(filtr)
        return (inequality_field, formatted_filters)


# - - - Endpoint methods - - - - - - - - - - - - - - - - -

# - - - Conferences - - -

    def _createConferenceObject(self, request):
        """Create a Conference object, return the ConferenceForm."""
        user = validateUser()
        user_id = getUserId(user)

        if not request.name:
            raise endpoints.BadRequestException("'name' field required")

        # Copy ConferenceForm/ProtoRPC Message into dict.
        data = {field.name: getattr(request, field.name)
                for field in request.all_fields()}

        del data['websafeKey']
        del data['organizerDisplayName']

        # Add default values for those missing.
        for df in DEFAULTS:
            if data[df] in (None, []):
                data[df] = DEFAULTS[df]
                setattr(request, df, DEFAULTS[df])

        # Convert dates from strings to Date objects.
        # Set month based on start_date.
        if data['startDate']:
            data['startDate'] = datetime.datetime.strptime(
                data['startDate'][:10], "%Y-%m-%d").date()
            data['month'] = data['startDate'].month
        else:
            data['month'] = 0

        if data['endDate']:
            data['endDate'] = datetime.datetime.strptime(
                data['endDate'][:10], "%Y-%m-%d").date()

        # Set seatsAvailable to be same as maxAttendees on creation.
        if data["maxAttendees"] > 0:
            data["seatsAvailable"] = data["maxAttendees"]

        # Generate Profile Key based on user ID and Conference
        # ID based on Profile key.
        p_key = ndb.Key(Profile, user_id)
        c_id = Conference.allocate_ids(size=1, parent=p_key)[0]
        c_key = ndb.Key(Conference, c_id, parent=p_key)
        data['key'] = c_key
        data['organizerUserId'] = request.organizerUserId = user_id

        # Create Conference, send email to organizer confirming
        # creation of Conference & return (modified) ConferenceForm
        Conference(**data).put()
        taskqueue.add(params={'email': user.email(),
                      'conferenceInfo': repr(request)},
                      url='/tasks/send_confirmation_email')

        return request


    def _copyConferenceToForm(self, conf, displayName):
        """Copy relevant fields from Conference to ConferenceForm."""
        cf = ConferenceForm()
        for field in cf.all_fields():
            if hasattr(conf, field.name):
                # Convert Date to date string; just copy others.
                if field.name.endswith('Date'):
                    setattr(cf, field.name, str(getattr(conf, field.name)))

                else:
                    setattr(cf, field.name, getattr(conf, field.name))

            elif field.name == "websafeKey":
                setattr(cf, field.name, conf.key.urlsafe())

        if displayName:
            setattr(cf, 'organizerDisplayName', displayName)

        cf.check_initialized()
        return cf


    @ndb.transactional()
    def _updateConferenceObject(self, request):
        user = validateUser()
        user_id = getUserId(user)

        # Copy ConferenceForm/ProtoRPC Message into dict.
        data = {field.name: getattr(request, field.name)
                for field in request.all_fields()}

        # Update existing conference.
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        self._validateOwner(request.websafeConferenceKey, user_id)

        # Not getting all the fields, so don't create a new object. Just
        # copy relevant fields from ConferenceForm to Conference object.
        for field in request.all_fields():
            data = getattr(request, field.name)
            # Only copy fields where we get data.

            if data not in (None, []):
                # Special handling for dates (convert string to Date).
                if field.name in ('startDate', 'endDate'):
                    data = datetime.datetime.strptime(data, "%Y-%m-%d").date()

                    if field.name == 'startDate':
                        conf.month = data.month

                # Write to Conference object.
                setattr(conf, field.name, data)

        conf.put()
        prof = ndb.Key(Profile, user_id).get()

        return self._copyConferenceToForm(conf, getattr(prof, 'displayName'))


    @endpoints.method(ConferenceForm, ConferenceForm, path='conference',
                      http_method='POST', name='createConference')
    def createConference(self, request):
        """Create new conference."""
        return self._createConferenceObject(request)


    @endpoints.method(CONF_POST_REQUEST, ConferenceForm,
                      path='conference/{websafeConferenceKey}',
                      http_method='PUT', name='updateConference')
    def updateConference(self, request):
        """Update conference w/provided fields & return w/updated info."""
        return self._updateConferenceObject(request)


    @endpoints.method(CONF_GET_REQUEST, ConferenceForm,
                      path='conference/{websafeConferenceKey}',
                      http_method='GET', name='getConference')
    def getConference(self, request):
        """Return requested conference (by websafeConferenceKey)."""
        # Get Conference object from request; bail if not found.
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        self._checkConf(conf)
        prof = conf.key.parent().get()

        return self._copyConferenceToForm(conf, getattr(prof, 'displayName'))

# - - - Sessions - - -

    def _createSessionObject(self, request):
        """Create Session object, return Session form."""
        user = validateUser()
        user_id = getUserId(user)

        # Collect data from request.
        data = {}
        for field in request.all_fields():
            value = getattr(request, field.name)
            # Value might be None, if not provided on creation.

            if value and field.name == 'date':
                data['date'] = datetime.datetime.strptime(
                    value, "%Y-%m-%d").date()

            elif value and field.name == 'startTime':
                data['startTime'] = datetime.datetime.strptime(
                    value, "%I:%M %p").time()

            elif value and field.name == 'speakers':
                data['speakers'] = self._addSpeakers(request, value)
            else:
                data[field.name] = value

        del data['websafeConferenceKey']

        # Check if conference exists and if user is its owner.
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        self._checkConf(conf)
        self._validateOwner(request.websafeConferenceKey, user_id)

        # Generate session key with the respective conference as parent.
        s_id = Session.allocate_ids(size=1, parent=conf.key)[0]
        s_key = ndb.Key(Session, s_id, parent=conf.key)
        data['key'] = s_key

        sess = Session(**data)
        sess.put()

        return self._copySessionToForm(sess)


    def _getSessions(self, wbck):
        """Get all sessions from a conference."""
        confkey = ndb.Key(urlsafe=wbck)
        self._checkConf(confkey.get())

        # Create ancestor query to retrieve all sessions for this conference.
        sessions = Session.query(ancestor=confkey)
        return sessions


    def _copySessionToForm(self, sess):
        """Copy relevant fields from Session to SessionForm."""
        cf = SessionForm()
        for field in cf.all_fields():
            if hasattr(sess, field.name):
                if field.name in ('date', 'startTime'):
                    setattr(cf, field.name, str(getattr(sess, field.name)))

                # Copy speaker names to form instead of their keys.
                elif field.name == 'speakers':
                    sp_names = [ndb.Key(urlsafe=sp).get().name for sp in
                                getattr(sess, 'speakers')]
                    setattr(cf, field.name, sp_names)

                else:
                    setattr(cf, field.name, getattr(sess, field.name))

        cf.check_initialized()
        return cf


    @endpoints.method(SESS_POST_REQUEST, SessionForm,
                      path='session/{websafeConferenceKey}',
                      http_method='POST', name='createSession')
    def createSession(self, request):
        """Create new session."""
        return self._createSessionObject(request)

# - - - Wishlists - - -

    @endpoints.method(WISH_POST_REQUEST, MultiStringMessage,
                      path='wishlist/{sessionKey}',
                      http_method='POST', name='addSessionToWishlist')
    def addSessionToWishlist(self, request):
        """Adds the session to the current user's wishlist."""
        validateUser()
        profile = self._getProfileFromUser(makeNew=False)

        # Check if session was already added.
        if request.sessionKey in profile.sessionWishlist:
            raise ConflictException(
                "This session is already on your wishlist.")

        # Add session to wishlist.
        profile.sessionWishlist.append(request.sessionKey)
        profile.put()

        session_names = [s.name for s in
                         ndb.get_multi(profile.sessionWishlist)]

        return MultiStringMessage(data=session_names)


    @endpoints.method(message_types.VoidMessage, MultiStringMessage,
                      http_method='GET', name='getSessionsInWishlist')
    def getSessionsInWishlist(self, request):
        """Get all sessions from the user's wishlist."""
        validateUser()
        profile = self._getProfileFromUser(makeNew=False)

        wish_keys = [ndb.Key(urlsafe=wsck) for wsck in
                     profile.sessionWishlist]

        session_names = [s.name for s in
                         ndb.get_multi(wish_keys)]

        return MultiStringMessage(data=session_names)

# - - - Queries - - -

    @endpoints.method(CONF_GET_REQUEST, MultiStringMessage,
                      path='bla/{websafeConferenceKey}',
                      http_method='GET', name='getConferenceSpeakers')
    def getConferenceSpeakers(self, request):
        """Return all speakers of a conference (by websafeConferenceKey)."""
        sessions = self._getSessions(
            request.websafeConferenceKey).fetch(projection=[Session.speakers])

        # Use a Python set to remove duplicates among speaker keys.
        unique_sp = set([sp for sess in sessions for sp in
                        sess.speakers])

        # Retrieve speaker objects from keys and return them.
        speakers = ndb.get_multi((ndb.Key(urlsafe=k) for k in unique_sp))
        return MultiStringMessage(data=[sp.name for sp in speakers])


    @endpoints.method(CONF_GET_REQUEST, SessionForms,
                      path='session/{websafeConferenceKey}',
                      http_method='GET', name='getConferenceSessions')
    def getConferenceSessions(self, request):
        """Return all sessions of a conference."""
        sessions = self._getSessions(request.websafeConferenceKey)

        # Return set of SessionForm objects per Session.
        return SessionForms(
            items=[self._copySessionToForm(sess) for sess in sessions]
        )


    @endpoints.method(TYPE_GET_REQUEST, SessionForms,
                      path='session/{websafeConferenceKey}/{sessionType}',
                      http_method='GET', name='getConferenceSessionsByType')
    def getConferenceSessionsByType(self, request):
        """Return all sessions of a particular type."""
        all_sessions = self._getSessions(request.websafeConferenceKey)
        type_sessions = all_sessions.filter(Session.typeOfSession ==
                                            request.sessionType)

        return SessionForms(
            items=[self._copySessionToForm(sess) for sess in type_sessions]
        )


    @endpoints.method(message_types.VoidMessage, MultiStringMessage,
                      http_method='GET', name='getNonWorkshops')
    def getNonWorkshops(self, request):
        """Get non-workshop sessions starting before 7pm."""
        # Retrieve all non-workshop sessions, then all sessions starting before
        # 7pm. Finally, make the intersection of both sets.
        non_workshop = Session.query(Session.typeOfSession != 'workshop')
        before_seven = Session.query(Session.startTime <= datetime.time(19, 0))
        intersect = set([n.key.urlsafe() for n in non_workshop]
                        ) & set([b.key.urlsafe() for b in before_seven])

        # Get session names and return them.
        sessions = ndb.get_multi((ndb.Key(urlsafe=s) for s in intersect))
        session_names = [s.name for s in sessions]

        return MultiStringMessage(data=session_names)


    @endpoints.method(SESS_GET_REQUEST, SessionForms,
                      path='speakers/{websafeSpeakerKey}',
                      http_method='GET', name='getSessionsBySpeaker')
    def getSessionsBySpeaker(self, request):
        """Return all sessions given by a particular speaker."""
        # Create query for all key matches for this speaker.
        sessions = Session.query(
            Session.speakers.IN([request.websafeSpeakerKey]))

        return SessionForms(
            items=[self._copySessionToForm(sess) for sess in sessions]
        )


    @endpoints.method(message_types.VoidMessage, ConferenceForms,
                      path='upcoming',
                      http_method='GET', name='getUpcomingConferences')
    def getUpcomingConferences(self, request):
        """Return upcoming conferences (this and next month)."""
        # Retrieve all conferences held at the current or the next month.
        cur_mo = datetime.datetime.now().month
        confs = Conference.query(Conference.month >= cur_mo,
                                 Conference.month <= cur_mo + 1)

        return ConferenceForms(
            items=[self._copyConferenceToForm(conf, '') for conf in confs]
        )


    @endpoints.method(message_types.VoidMessage, ConferenceForms,
                      path='getConferencesCreated',
                      http_method='GET', name='getConferencesCreated')
    def getConferencesCreated(self, request):
        """Return conferences created by user."""
        user = validateUser()
        user_id = getUserId(user)

        # Create ancestor query for all key matches for this user.
        confs = Conference.query(ancestor=ndb.Key(Profile, user_id))
        prof = ndb.Key(Profile, user_id).get()

        return ConferenceForms(
            items=[self._copyConferenceToForm(
                conf, getattr(prof, 'displayName')) for conf in confs])


    @endpoints.method(ConferenceQueryForms, ConferenceForms,
                      path='queryConferences',
                      http_method='POST',
                      name='queryConferences')
    def queryConferences(self, request):
        """Query for conferences."""
        conferences = self._getQuery(request)

        # Fetch organiser displayName from profiles.
        # Get all keys and use get_multi for speed.
        organisers = [(ndb.Key(Profile, conf.organizerUserId))
                      for conf in conferences]
        profiles = ndb.get_multi(organisers)

        # Put display names in a dict for easier fetching.
        names = {}
        for profile in profiles:
            names[profile.key.id()] = profile.displayName

        # Return individual ConferenceForm object per Conference.
        return ConferenceForms(
            items=[self._copyConferenceToForm(
                conf, names[conf.organizerUserId])
                for conf in conferences])


# - - - Profile objects - - - - - - - - - - - - - - - - - - -

    def _copyProfileToForm(self, prof):
        """Copy relevant fields from Profile to ProfileForm."""
        pf = ProfileForm()

        for field in pf.all_fields():
            if hasattr(prof, field.name):
                # Convert t-shirt string to Enum; just copy others
                if field.name == 'teeShirtSize':
                    setattr(pf, field.name, getattr(
                        TeeShirtSize, getattr(prof, field.name)))
                else:
                    setattr(pf, field.name, getattr(prof, field.name))

        pf.check_initialized()
        return pf


    def _getProfileFromUser(self, makeNew=True):
        """Return user Profile from datastore, creating new one if needed."""
        user = validateUser()
        user_id = getUserId(user)

        p_key = ndb.Key(Profile, user_id)
        profile = p_key.get()

        # create new Profile if not there
        if not profile and makeNew:
            profile = Profile(
                key=p_key,
                displayName=user.nickname(),
                mainEmail=user.email(),
                teeShirtSize=str(TeeShirtSize.NOT_SPECIFIED),
            )
            profile.put()

        return profile


    def _doProfile(self, save_request=None):
        """Get user Profile and return to user, possibly updating it first."""
        # Get user Profile
        prof = self._getProfileFromUser()

        # If saveProfile(), process user-modifyable fields.
        if save_request:
            for field in ('displayName', 'teeShirtSize'):

                if hasattr(save_request, field):
                    val = getattr(save_request, field)

                    if val:
                        setattr(prof, 'displayName', str(val))
                        if field == 'teeShirtSize':
                            setattr(prof, field, str(val).upper())
                        else:
                            setattr(prof, field, val)

                        prof.put()

        return self._copyProfileToForm(prof)


    @endpoints.method(message_types.VoidMessage, ProfileForm,
                      path='profile', http_method='GET', name='getProfile')
    def getProfile(self, request):
        """Return user profile."""
        return self._doProfile()


    @endpoints.method(ProfileMiniForm, ProfileForm,
                      path='profile', http_method='POST', name='saveProfile')
    def saveProfile(self, request):
        """Update & return user profile."""
        return self._doProfile(request)


# - - - Announcements - - - - - - - - - - - - - - - - - - - -

    @staticmethod
    def _cacheAnnouncement():
        """Create Announcement & assign to memcache; used by
        memcache cron job & putAnnouncement().
        """
        confs = Conference.query(ndb.AND(
            Conference.seatsAvailable <= 5,
            Conference.seatsAvailable > 0)
        ).fetch(projection=[Conference.name])

        if confs:
            # If there are almost sold out conferences,
            # format announcement and set it in memcache
            announcement = ANNOUNCEMENT_TPL % (
                ', '.join(conf.name for conf in confs))
            memcache.set(MEMCACHE_ANNOUNCEMENTS_KEY, announcement)
        else:
            # If there are no sold out conferences,
            # delete the memcache announcements entry
            announcement = ""
            memcache.delete(MEMCACHE_ANNOUNCEMENTS_KEY)

        return announcement


    @endpoints.method(CONF_GET_REQUEST, StringMessage,
                      path='feature/{websafeConferenceKey}', http_method='GET',
                      name='getFeaturedSpeaker')
    def getFeaturedSpeaker(self, request):
        """Return featured speaker from memcache."""
        cache_entry = memcache.get(request.websafeConferenceKey)

        # If there is a featured speaker in memcache, return its name.
        if cache_entry:
            return StringMessage(data=cache_entry.split('|')[0])
        else:
            return StringMessage(data='')


    @endpoints.method(message_types.VoidMessage, StringMessage,
                      path='conference/announcement/get',
                      http_method='GET', name='getAnnouncement')
    def getAnnouncement(self, request):
        """Return Announcement from memcache."""
        return StringMessage(data=memcache.get(
            MEMCACHE_ANNOUNCEMENTS_KEY) or "")


# - - - Registration - - - - - - - - - - - - - - - - - - - -

    @ndb.transactional(xg=True)
    def _conferenceRegistration(self, request, reg=True):
        """Register or unregister user for selected conference."""
        retval = None
        prof = self._getProfileFromUser()

        # Check if conf exists
        wsck = request.websafeConferenceKey
        conf = ndb.Key(urlsafe=wsck).get()
        self._checkConf(conf)

        # Register
        if reg:
            # Check if user already registered otherwise add.
            if wsck in prof.conferenceKeysToAttend:
                raise ConflictException(
                    "You have already registered for this conference")

            # Check if seats available.
            if conf.seatsAvailable <= 0:
                raise ConflictException(
                    "There are no seats available.")

            # Register user, take away one seat.
            prof.conferenceKeysToAttend.append(wsck)
            conf.seatsAvailable -= 1
            retval = True

        # Unregister
        else:
            # Check if user already registered.
            if wsck in prof.conferenceKeysToAttend:

                # Unregister user, add back one seat.
                prof.conferenceKeysToAttend.remove(wsck)
                conf.seatsAvailable += 1
                retval = True
            else:
                retval = False

        # Write things back to the datastore & return.
        prof.put()
        conf.put()
        return BooleanMessage(data=retval)


    @endpoints.method(message_types.VoidMessage, ConferenceForms,
                      path='conferences/attending',
                      http_method='GET', name='getConferencesToAttend')
    def getConferencesToAttend(self, request):
        """Get list of conferences that user has registered for."""
        prof = self._getProfileFromUser()
        conf_keys = [ndb.Key(urlsafe=wsck) for wsck in
                     prof.conferenceKeysToAttend]
        conferences = ndb.get_multi(conf_keys)

        # Get organizers
        organisers = [ndb.Key(Profile, conf.organizerUserId)
                      for conf in conferences]
        profiles = ndb.get_multi(organisers)

        # Put display names in a dict for easier fetching.
        names = {}
        for profile in profiles:
            names[profile.key.id()] = profile.displayName

        return ConferenceForms(
            items=[self._copyConferenceToForm(
                conf, names[conf.organizerUserId])
                for conf in conferences])


    @endpoints.method(CONF_GET_REQUEST, BooleanMessage,
                      path='conference/{websafeConferenceKey}',
                      http_method='POST', name='registerForConference')
    def registerForConference(self, request):
        """Register user for selected conference."""
        return self._conferenceRegistration(request)


    @endpoints.method(CONF_GET_REQUEST, BooleanMessage,
                      path='conference/{websafeConferenceKey}',
                      http_method='DELETE', name='unregisterFromConference')
    def unregisterFromConference(self, request):
        """Unregister user for selected conference."""
        return self._conferenceRegistration(request, reg=False)


api = endpoints.api_server([ConferenceApi])
