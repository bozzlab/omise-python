import copy
import logging
import os
import requests
import sys
from . import version
from . import errors


if sys.version_info[0] == 3:
    import urllib.parse as urlparse

    def iteritems(d, **kw):
        return iter(d.items(**kw))

elif sys.version_info[0] == 2:
    import urlparse

    def iteritems(d, **kw):
        return iter(d.iteritems(**kw))


try:
    basestring
except NameError:
    basestring = str


# Settings
api_secret = None
api_public = None


# API constants
api_compat = '2014-07-27'
api_main = 'https://api.omise.co'
api_vault = 'https://vault.omise.co'


# Logging
logging.basicConfig()
logger = logging.getLogger(__name__)


__all__ = [
    'Account',
    'Balance',
    'Card',
    'Charge',
    'Collection',
    'Customer',
    'Refund',
    'Token',
    'Transaction',
    'Transfer',
]


def _get_class_for(type):
    """Returns a :type:`class` corresponding to :param:`type`.

    Used for getting a class from object type in JSON response. Usually, to
    instantiate the Python object from response, this function is called in
    the form of ``_get_class_for(data['object']).from_data(data)``.

    :type type: str
    :rtype: class
    """
    return {
        'account': Account,
        'balance': Balance,
        'token': Token,
        'card': Card,
        'charge': Charge,
        'customer': Customer,
        'refund': Refund,
        'transfer': Transfer,
        'transaction': Transaction,
        'list': Collection,
    }.get(type)


def _as_object(data):
    """Returns a Python :type:`object` from API response.

    Accepts a :type:`dict` returned from Omise API and instantiate it as
    Python object using the class returned from :func:`_get_class_for`.

    :type data: dict | list
    :rtype: T <= Base
    """
    if isinstance(data, list):
        return [_as_object(i) for i in data]
    elif isinstance(data, dict):
        class_ = _get_class_for(data['object'])
        if not class_:
            class_ = Base
        return class_.from_data(data)
    return data


class Request(object):
    """API requestor that construct and make a request to API endpoint.

    Construct an API endpoint and authentication header using the given
    ``api_key`` and ``api_base`` and allow user to make a request to that
    endpoint.

    Basic usage::

        >>> import omise
        >>> r = omise.Request('skey_test', 'http://api.omise.co/')
        >>> r.send('get', 'account')
        {'email': 'foo@example.com', 'object': 'account', ...}
    """

    def __init__(self, api_key, api_base):
        if api_key is None:
            raise AttributeError('API key is not set.')
        self.api_key = api_key
        self.api_base = api_base

    def send(self, method, path, payload=None, headers=None):
        """Make a request to the API endpoint and return a JSON response.

        This method will construct a URL using :param:`path` and make a request
        to that endpoint using HTTP method set in :param:`method` with
        necessary headers set. The JSON returned from the API server will
        be serialized into :type:`dict`.

        If :param:`payload` is given, that payload will be passed alongside
        the request regardless of HTTP method used. Custom headers are
        assignable via :param:`headers`, however please note that ``Accept``,
        ``Content-Type`` and ``User-Agent`` are not overridable.

        In case the response is an error, an appropriate exception from
        :module:`omise.errors` will be raised. The application code is
        responsible for handling these exceptions.

        :param method: method for the request.
        :param path: path components relative to API base to make the request.
        :param payload: (optional) dict containing data to send to the server.
        :param headers: (optional) dict containing custom headers.

        :type method: str
        :type path: str or list or tuple
        :type payload: dict or None
        :type headers: dict or None
        :rtype: dict
        """
        request_path = self._build_path(path)
        request_payload = self._build_payload(payload)
        request_headers = self._build_headers(headers)

        logger.info('Sending HTTP request: %s %s', method.upper(), request_path)
        logger.debug('Authorization: %s', self.api_key)
        logger.debug('Payload: %s', request_payload)
        logger.debug('Headers: %s', request_headers)

        response = getattr(requests, method)(
            request_path,
            data=request_payload,
            headers=request_headers,
            auth=(self.api_key, None),
            verify=os.path.join(
                os.path.dirname(__file__),
                'data/ca_certificates.pem')
        ).json()

        logger.info('Received HTTP response: %s', response)

        if response.get('object') == 'error':
            errors._raise_from_data(response)
        return response

    def _build_path(self, path):
        if not hasattr(path, '__iter__') or isinstance(path, basestring):
            path = (path,)
        path = map(str, path)
        return urlparse.urljoin(self.api_base, '/'.join(path))

    def _build_payload(self, payload):
        if payload is None:
            payload = {}
        return payload

    def _build_headers(self, headers):
        if headers is None:
            headers = {}
        headers['Accept'] = 'application/json'
        headers['User-Agent'] = 'OmisePython/%s OmiseAPI/%s' % (
            version.__VERSION__,
            api_compat)
        return headers


class Base(object):
    """Provides a base class for all API classes.

    The base class that all API classes inherit from. The instance of
    this class proxies its attributes access to :type:`dict` and also
    track changes made to it.

    Basic usage::

        >>> import omise
        >>> obj = omise.Base.from_data({'id': 'test'})
        <Base id='test' at 0x7f0d931cf740>
        >>> obj.id
        'test'
    """

    def __init__(self):
        super(Base, self).__init__()
        self._attributes = dict()
        self._changes = set()

    def __setattr__(self, key, value):
        if key[0] == '_':
            super(Base, self).__setattr__(key, value)
        else:
            self._changes.add(key)
            self._attributes[key] = value

    def __getattr__(self, key):
        if key[0] == '_':
            raise AttributeError(key)
        try:
            value = self._attributes[key]
            if isinstance(value, dict):
                return _as_object(value)
            return value
        except KeyError as e:
            raise AttributeError(*e.args)

    def __repr__(self):
        id_ = self._attributes.get('id')
        return '<%s%s at %s>' % (
            type(self).__name__,
            ' id=%s' % repr(str(id_)) if id_ else '',
            hex(id(self)))

    @classmethod
    def from_data(cls, data):
        """Instantiate the class with the given data.

        Creates a new instance of this class with :param:`data` assigned to it.
        This method is what is called after the data is retrieved from the API.

        :param data: data to instantiate this class with.
        :type data: dict
        """
        instance = cls()
        instance._reload_data(data)
        return instance

    @classmethod
    def _request(cls):
        return NotImplementedError

    @classmethod
    def _collection_path(cls):
        return NotImplementedError

    @classmethod
    def _instance_path(cls, *args):
        raise NotImplementedError

    def _reload_data(self, data):
        self._attributes = dict()
        for k, v in iteritems(data):
            self._attributes[k] = v
        self._changes = set()
        return self

    @property
    def changes(self):
        """Property that returns a :type:`dict` of attributes pending update.

        This method is used to track changes made to attribute of an instance
        which is often used to determine which attributes to update on the
        server when :method:`update` is called.

        :rtype: dict
        """
        return dict((c, self._attributes.get(c)) for c in self._changes)


class _MainResource(Base):

    @classmethod
    def _request(cls, *args, **kwargs):
        return Request(api_secret, api_main).send(*args, **kwargs)


class _VaultResource(Base):

    @classmethod
    def _request(cls, *args, **kwargs):
        return Request(api_public, api_vault).send(*args, **kwargs)


class Account(_MainResource, Base):
    """API class representing accounts details.

    This API class is used for retrieving account information such as creator
    email or account creation date. The account retrieved by this API is the
    account associated with API secret key.

    Basic usage::

        >>> import omise
        >>> omise.api_secret = 'skey_test_4xs8breq3htbkj03d2x'
        >>> account = omise.Account.retrieve()
        <Account id='acct_4xs8bre8a8vhrgijcjg' at 0x7f7410021990>
        >>> account.email
        None
    """

    @classmethod
    def _instance_path(cls, *args):
        return 'account'

    @classmethod
    def retrieve(cls):
        """Retrieve the account details associated with the API key.

        :rtype: Account
        """
        return _as_object(cls._request('get', cls._instance_path()))

    def reload(self):
        """Reload the account details.

        :rtype: Account
        """
        return self._reload_data(self._request('get', self._instance_path()))


class Balance(_MainResource, Base):
    """API class representing balance details.

    This API class is used for retrieving current balance of the account.
    Balance do not have ID associated to it and is immutable.

    Basic usage::

        >>> import omise
        >>> omise.api_secret = 'skey_test_4xs8breq3htbkj03d2x'
        >>> balance = omise.Balance.retrieve()
        <Balance at 0x7f7410021868>
        >>> balance.total
        0
    """

    @classmethod
    def _instance_path(cls, *args):
        return 'balance'

    @classmethod
    def retrieve(cls):
        """Retrieve the balance details for current account.

        :rtype: Balance
        """
        return _as_object(cls._request('get', cls._instance_path()))

    def reload(self):
        """Reload the balance details.

        :rtype: Balance
        """
        return self._reload_data(self._request('get', self._instance_path()))


class Token(_VaultResource, Base):
    """API class for creating and retrieving credit card token with the API.

    Credit card tokens are a unique ID that represents a card that could
    be used in place of where a card is required. Token can be used only
    once and invoked immediately after it is used.

    This API class is used for retrieving and creating token representing
    a card with the vault API. Unlike most other API, this API requires the
    public key to be set in ``omise.api_public``.

    Basic usage::

        >>> import omise
        >>> omise.api_public = 'pkey_test_4xs8breq32civvobx15'
        >>> token = omise.Token.retrieve('tokn_test_4xs9408a642a1htto8z')
        <Token id='tokn_test_4xs9408a642a1htto8z' at 0x7f406b384990>
        >>> token.used
        False
    """

    @classmethod
    def _collection_path(cls):
        return 'tokens'

    @classmethod
    def _instance_path(cls, token_id):
        return ('tokens', token_id)

    @classmethod
    def create(cls, **kwargs):
        """Create a credit card token with the given card details.

        In production environment, the token should be created with
        `Omise.js <https://docs.omise.co/omise-js>`_ and credit card details
        should never go through your server. This method should only be used
        for creating fake data in test mode.

        See the `create a token`_ section in the API documentation for list
        of available arguments.

        Basic usage::

            >>> import omise
            >>> omise.api_public = 'pkey_test_4xs8breq32civvobx15'
            >>> token = omise.Token.create(
            ...     name='Somchai Prasert',
            ...     number='4242424242424242',
            ...     expiration_month=10,
            ...     expiration_year=2018,
            ...     city='Bangkok',
            ...     postal_code='10320',
            ...     security_code=123
            ... )
            <Token id='tokn_test_4xs9408a642a1htto8z' at 0x7f406b384990>

        .. _create a token: https://docs.omise.co/api/tokens/#create-a-token

        :param \*\*kwargs: arguments to create a token.
        :rtype: Token
        """
        transformed_args = {}
        for key, value in iteritems(kwargs):
            transformed_args['card[%s]' % key] = value
        return _as_object(
            cls._request('post',
                         cls._collection_path(),
                         transformed_args))

    @classmethod
    def retrieve(cls, token_id):
        """Retrieve the token details for the given :param:`token_id`.

        :param token_id: a token id to retrieve.
        :type token_id: str
        :rtype: Token
        """
        return _as_object(cls._request('get', cls._instance_path(token_id)))

    def reload(self):
        """Reload the token details.

        :rtype: Token
        """
        return self._reload_data(
            self._request('get',
                          self._instance_path(self._attributes['id'])))


class Card(_MainResource, Base):
    """API class representing card details.

    This API class represents a card information returned from other APIs.
    Cards are not created directly with this class, but instead created with
    :class:`Token`.

    Basic usage::

        >>> import omise
        >>> omise.api_secret = 'skey_test_4xsjvwfnvb2g0l81sjz'
        >>> customer = omise.Customer.retrieve('cust_test_4xsjvylia03ur542vn6')
        >>> card = customer.cards.retrieve('card_test_4xsjw0t21xaxnuzi9gs')
        <Card id='card_test_4xsjw0t21xaxnuzi9gs' at 0x7f406b384ab8>
        >>> card.last_digits
        '4242'
    """

    def reload(self):
        """Reload the card details.

        :rtype: Card
        """
        return self._reload_data(
            self._request('get',
                          self._attributes['location']))

    def update(self, **kwargs):
        """Update the card information with the given card details.

        See the `update a card`_ section in the API documentation for list
        of available arguments.

        Basic usage::

            >>> import omise
            >>> omise.api_secret = 'skey_test_4xsjvwfnvb2g0l81sjz'
            >>> cust = omise.Customer.retrieve('cust_test_4xsjvylia03ur542vn6')
            >>> card = cust.cards.retrieve('card_test_4xsjw0t21xaxnuzi9gs')
            >>> card.update(
            ...     expiration_month=11,
            ...     expiration_year=2017,
            ...     name='Somchai Praset',
            ...     postal_code='10310'
            ... )
            <Card id='card_test_4xsjw0t21xaxnuzi9gs' at 0x7f7911746ab8>

        :param \*\*kwargs: arguments to update a card.
        :rtype: Card

        .. _update a card: https://docs.omise.co/api/cards/#update-a-card
        """
        changed = copy.deepcopy(self.changes)
        changed.update(kwargs)
        return self._reload_data(
            self._request('patch',
                          self._attributes['location'],
                          changed))

    def destroy(self):
        """Delete the card and unassociated it from the customer.

        Basic usage::

            >>> import omise
            >>> omise.api_secret = 'skey_test_4xsjvwfnvb2g0l81sjz'
            >>> cust = omise.Customer.retrieve('cust_test_4xsjvylia03ur542vn6')
            >>> card = cust.cards.retrieve('card_test_4xsjw0t21xaxnuzi9gs')
            >>> card.destroy()
            <Card id='card_test_4xsjw0t21xaxnuzi9gs' at 0x7f7911746868>
            >>> card.destroyed
            True

        :rtype: Card
        """
        return self._reload_data(
            self._request('delete',
                          self._attributes['location']))

    @property
    def destroyed(self):
        """Returns ``True`` if card has been deleted.

        :rtype: bool
        """
        return self._attributes.get('deleted', False)


class Charge(_MainResource, Base):
    """API class representing a charge.

    This API class is used for retrieving and creating a charge to the
    specific credit card. There are two modes of a charge: authorize and
    capture. Authorize is for holding an amount of a charge in credit card's
    available balance and capture for capturing that authorized amount.

    Basic usage::

        >>> import omise
        >>> omise.api_secret = 'skey_test_4xsjvwfnvb2g0l81sjz'
        >>> charge = omise.Charge.retrieve('chrg_test_4xso2s8ivdej29pqnhz')
        <Charge id='chrg_test_4xso2s8ivdej29pqnhz' at 0x7fed3241b990>
        >>> charge.amount
        100000
    """

    @classmethod
    def _collection_path(cls):
        return 'charges'

    @classmethod
    def _instance_path(cls, charge_id):
        return ('charges', charge_id)

    @classmethod
    def create(cls, **kwargs):
        """Create a charge to the given card details.

        See the `create a charge`_ section in the API documentation for list
        of available arguments.

        Basic usage::

            >>> import omise
            >>> omise.api_secret = 'skey_test_4xsjvwfnvb2g0l81sjz'
            >>> charge = omise.Charge.create(
            ...     amount=100000,
            ...     currency='thb',
            ...     description='Order-384',
            ...     ip='127.0.0.1',
            ...     card='tokn_test_4xs9408a642a1htto8z',
            ... )
            <Charge id='chrg_test_4xso2s8ivdej29pqnhz' at 0x7fed3241b868>

        .. _create a charge: https://docs.omise.co/api/charges/#create-a-charge

        :param \*\*kwargs: arguments to create a charge.
        :rtype: Charge
        """
        return _as_object(
            cls._request('post',
                         cls._collection_path(),
                         kwargs))

    @classmethod
    def retrieve(cls, charge_id=None):
        """Retrieve the charge details for the given :param:`charge_id`.

        :param charge_id: a charge id to retrieve.
        :type charge_id: str
        :rtype: Charge
        """
        if charge_id:
            return _as_object(
                cls._request('get',
                             cls._instance_path(charge_id)))
        return _as_object(cls._request('get', cls._collection_path()))

    def reload(self):
        """Reload the charge details.

        :rtype: Charge
        """
        return self._reload_data(
            self._request('get',
                          self._instance_path(self._attributes['id'])))

    def update(self, **kwargs):
        """Update the charge details with the given arguments.

        See the `update a charge`_ section in the API documentation for list
        of available arguments.

        Basic usage::

            >>> import omise
            >>> omise.api_secret = 'skey_test_4xsjvwfnvb2g0l81sjz'
            >>> charge = omise.Charge.retrieve('chrg_test_4xso2s8ivdej29pqnhz')
            >>> charge.update(description='Another description')
            <Charge id='chrg_test_4xso2s8ivdej29pqnhz' at 0x7fed3241bab8>

        :param \*\*kwargs: arguments to update a charge.
        :rtype: Charge

        .. _update a charge: https://docs.omise.co/api/charges/#update-a-charge
        """
        changed = copy.deepcopy(self.changes)
        changed.update(kwargs)
        return self._reload_data(
            self._request('patch',
                          self._instance_path(self._attributes['id']),
                          changed))

    def capture(self):
        """Capture an authorized charge.

        :rtype: Charge
        """
        path = self._instance_path(self._attributes['id']) + ('capture',)
        return self._reload_data(self._request('post', path))

    def refund(self, **kwargs):
        """Refund a refundable charge.

        See the `create a refund`_ section in the API documentation for list of
        available arguments.

        :rtype: Refund

        .. _create a refund: https://docs.omise.co/api/refunds/#create-a-refund
        """
        path = self._instance_path(self._attributes['id']) + ('refunds',)
        refund = _as_object(self._request('post', path, kwargs))
        self.reload()
        return refund


class Collection(Base):
    """Proxy class representing a collection of items."""

    def __len__(self):
        return len(self._attributes['data'])

    def __iter__(self):
        for obj in self._attributes['data']:
            yield _as_object(obj)

    def __getitem__(self, item):
        return _as_object(self._attributes['data'][item])

    def retrieve(self, object_id=None):
        """Retrieve the specific :param:`object_id` from the list of objects.

        If no :param:`object_id` is given, a list of all objects will be
        returned instead. This is equivalent of calling ``list(collection)``.

        :param object_id: an object id to retrieve.
        :type object_id: str
        :rtype: T <= Base
        """
        if object_id is None:
            return list(self)
        else:
            for obj in self._attributes['data']:
                if obj['id'] == object_id:
                    return _as_object(obj)


class Customer(_MainResource, Base):
    """API class representing a customer in an account.

    This API class is used for retrieving and creating a customer in an
    account. The customer can be used for storing credit card details
    (using token) for later use.

    Basic usage::

        >>> import omise
        >>> omise.api_secret = 'skey_test_4xsjvwfnvb2g0l81sjz'
        >>> customer = omise.Customer.retrieve('cust_test_4xtrb759599jsxlhkrb')
        <Customer id='cust_test_4xtrb759599jsxlhkrb' at 0x7fb02625f990>
        >>> customer.email
        'john.doe@example.com'
    """

    @classmethod
    def _collection_path(cls):
        return 'customers'

    @classmethod
    def _instance_path(cls, customer_id):
        return ('customers', customer_id)

    @classmethod
    def create(cls, **kwargs):
        """Create a customer with the given card token.

        See the `create a customer`_ section in the API documentation for list
        of available arguments.

        Basic usage::

            >>> import omise
            >>> omise.api_secret = 'skey_test_4xsjvwfnvb2g0l81sjz'
            >>> customer = omise.Customer.create(
            ...     description='John Doe (id: 30)',
            ...     email='john.doe@example.com',
            ...     card='tokn_test_4xs9408a642a1htto8z',
            ... )
            <Customer id='cust_test_4xtrb759599jsxlhkrb' at 0x7fb02625fab8>

        .. _create a customer:
        ..     https://docs.omise.co/api/customers/#create-a-customer

        :param \*\*kwargs: arguments to create a customer.
        :rtype: Customer
        """
        return _as_object(
            cls._request('post',
                         cls._collection_path(),
                         kwargs))

    @classmethod
    def retrieve(cls, customer_id):
        """Retrieve the customer details for the given :param:`customer_id`.

        :param customer_id: a customer id to retrieve.
        :type customer_id: str
        :rtype: Customer
        """
        return _as_object(cls._request('get', cls._instance_path(customer_id)))

    def reload(self):
        """Reload the customer details.

        :rtype: Customer
        """
        return self._reload_data(
            self._request('get',
                          self._instance_path(self._attributes['id'])))

    def update(self, **kwargs):
        """Update the customer details with the given arguments.

        See the `update a customer`_ section in the API documentation for list
        of available arguments.

        Basic usage::

            >>> import omise
            >>> omise.api_secret = 'skey_test_4xsjvwfnvb2g0l81sjzx'
            >>> cust = omise.Customer.retrieve('cust_test_4xtrb759599jsxlhkrb')
            >>> cust.update(
            ...     email='john.smith@example.com',
            ...     description='Another description',
            ... )
            <Customer id='cust_test_4xtrb759599jsxlhkrb' at 0x7f319de7f990>

        :param \*\*kwargs: arguments to update a customer.
        :rtype: Customer

        .. _update a customer:
        ..     https://docs.omise.co/api/customers/#update-a-customer
        """
        changed = copy.deepcopy(self.changes)
        changed.update(kwargs)
        return self._reload_data(
            self._request('patch',
                          self._instance_path(self._attributes['id']),
                          changed))

    def destroy(self):
        """Delete the customer from the server.

        Basic usage::

            >>> import omise
            >>> omise.api_secret = 'skey_test_4xsjvwfnvb2g0l81sjzx'
            >>> cust = omise.Customer.retrieve('cust_test_4xtrb759599jsxlhkrb')
            >>> cust.destroy()
            <Customer id='cust_test_4xtrb759599jsxlhkrb' at 0x7ff72d8d1990>
            >>> cust.destroyed
            True

        :rtype: Customer
        """
        return self._reload_data(
            self._request('delete',
                          self._instance_path(self._attributes['id'])))

    @property
    def destroyed(self):
        """Returns ``True`` if customer has been deleted.

        :rtype: bool
        """
        return self._attributes.get('deleted', False)


class Refund(_MainResource, Base):
    """API class representing refund information.

    This API class represents a refund information returned from the refund API.
    Refunds are not created directly with this class, but instead can be created
    using :meth:`Charge.refund`.

    Basic usage::

        >>> import omise
        >>> omise.api_secret = 'skey_test_4xsjvwfnvb2g0l81sjz'
        >>> charge = omise.Charge.retrieve('chrg_test_4xso2s8ivdej29pqnhz')
        >>> refund = charge.refunds.retrieve('rfnd_test_4ypcvo03ktuw0uki7un')
        <Refund id='rfnd_test_4ypcvo03ktuw0uki7un' at 0x7fd6095096f8>
        >>> refund.amount
        10000
    """

    def reload(self):
        """Reload the refund details.

        :rtype: Refund
        """
        return self._reload_data(
            self._request('get',
                          self._attributes['location']))


class Transfer(_MainResource, Base):
    """API class representing a transfer.

    This API class is used for retrieving a transfer information and create
    a transfer to the bank account given in account settings. The transfer
    amount must always be less than the current balance.

    Basic usage::

        >>> import omise
        >>> omise.api_secret = 'skey_test_4xsjvwfnvb2g0l81sjz'
        >>> transfer = omise.Transfer.retrieve('trsf_test_4xs5px8c36dsanuwztf')
        <Transfer id='trsf_test_4xs5px8c36dsanuwztf' at 0x7ff72d8d1868>
        >>> transfer.amount
        50000
    """

    @classmethod
    def _collection_path(cls):
        return 'transfers'

    @classmethod
    def _instance_path(cls, transfer_id):
        return ('transfers', transfer_id)

    @classmethod
    def create(cls, **kwargs):
        """Create a transfer to the bank account.

        See the `create a transfer`_ section in the API documentation for list
        of available arguments.

        Basic usage::

            >>> import omise
            >>> omise.api_secret = 'skey_test_4xsjvwfnvb2g0l81sjz'
            >>> transfer = omise.Transfer.create(amount=100000)
            <Transfer id='trsf_test_4y3miv1nhy0dceit4w4' at 0x7f6ef55b0990>

        .. _create a transfer:
        ..     https://docs.omise.co/api/transfers/#create-a-transfer

        :param \*\*kwargs: arguments to create a transfer.
        :rtype: Transfer
        """
        return _as_object(
            cls._request('post',
                         cls._collection_path(),
                         kwargs))

    @classmethod
    def retrieve(cls, transfer_id=None):
        """Retrieve the transfer details for the given :param:`transfer_id`.
        If :param:`transfer_id` is not given, all transfers will be returned
        instead.

        :param transfer_id: (optional) a transfer id to retrieve.
        :type transfer_id: str
        :rtype: Transfer
        """
        if transfer_id:
            return _as_object(
                cls._request('get',
                             cls._instance_path(transfer_id)))
        return _as_object(cls._request('get', cls._collection_path()))

    def reload(self):
        """Reload the transfer details.

        :rtype: Transfer
        """
        return self._reload_data(
            self._request('get',
                          self._instance_path(self._attributes['id'])))

    def update(self, **kwargs):
        """Update the transfers details with the given arguments.

        This method will update the transfer if it is still in the pending
        state (i.e. not sent or paid.) An attempt to update a non-pending
        transfers will result in an error.

        See the `update a transfer`_ section in the API documentation for list
        of available arguments.

        Basic usage::

            >>> import omise
            >>> omise.api_secret = 'skey_test_4xsjvwfnvb2g0l81sjz'
            >>> trsf = omise.Transfer.retrieve('trsf_test_4xs5px8c36dsanuwztf')
            >>> trsf.update(amount=50000)
            <Transfer id='trsf_test_4xs5px8c36dsanuwztf' at 0x7f037c6c9f90>

        :param \*\*kwargs: arguments to update the transfer.
        :rtype: Customer

        .. _update a transfer:
        ..     https://docs.omise.co/api/transfers/#update-a-transfer
        """
        changed = copy.deepcopy(self.changes)
        changed.update(kwargs)
        return self._reload_data(
            self._request('patch',
                          self._instance_path(self.id),
                          changed))

    def destroy(self):
        """Delete the transfer from the server if it is not yet sent.

        This method will cancel the transfer if it is still in the pending
        state (i.e. not sent or paid.) An attempt to delete a non-pending
        transfers will result in an error.

        Basic usage::

            >>> import omise
            >>> omise.api_secret = 'skey_test_4xsjvwfnvb2g0l81sjz'
            >>> trsf = omise.Transfer.retrieve('trsf_test_4y3miv1nhy0dceit4w4')
            >>> trsf.destroy()
            <Transfer id='trsf_test_4y3miv1nhy0dceit4w4' at 0x7f037f8707d0>
            >>> trsf.destroyed
            True

        :rtype: Customer
        """
        return self._reload_data(
            self._request('delete',
                          self._instance_path(self.id)))

    @property
    def destroyed(self):
        """Returns ``True`` if the transfer has been deleted.

        :rtype: bool
        """
        return self._attributes.get('deleted', False)


class Transaction(_MainResource, Base):
    """API class representing a transaction.

    This API class is used for retrieving a transaction information for
    bookkeeping such as that made by :class:`Charge` and :class:`Transfer`
    operations.

    Basic usage::

        >>> import omise
        >>> omise.api_secret = 'skey_test_4xsjvwfnvb2g0l81sjz'
        >>> omise.Transaction.retrieve()
        <Collection at 0x7f6ef55b0ab8>
        >>> omise.Transaction.retrieve('trxn_test_4xuy2z4w5vmvq4x5pfs')
        <Transaction id='trxn_test_4xuy2z4w5vmvq4x5pfs' at 0x7fd953fa1990>
    """

    @classmethod
    def _collection_path(cls):
        return 'transactions'

    @classmethod
    def _instance_path(cls, transaction_id):
        return ('transactions', transaction_id)

    @classmethod
    def retrieve(cls, transaction_id=None):
        """Retrieve the transaction details for the given
        :param:`transaction_id`. If :param:`transaction_id` is not given, all
        transactions will be returned instead.

        :param transaction_id: (optional) a transaction id to retrieve.
        :type transaction_id: str
        :rtype: Transaction
        """
        if transaction_id:
            return _as_object(
                cls._request('get',
                             cls._instance_path(transaction_id)))
        return _as_object(cls._request('get', cls._collection_path()))

    def reload(self):
        """Reload the transaction details.

        :rtype: Transaction
        """
        return self._reload_data(
            self._request('get',
                          self._instance_path(self._attributes['id'])))