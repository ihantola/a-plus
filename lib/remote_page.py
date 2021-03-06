import logging
import posixpath
import re
import requests
import time
import urllib.parse
from bs4 import BeautifulSoup
from django.conf import settings
from django.utils.translation import ugettext_lazy as _


logger = logging.getLogger("aplus.remote_page")


class RemotePageException(Exception):

    def __init__(self, message):
        self.message = message


class RemotePage:
    """
    Represents a page that can be loaded over HTTP for further processing.
    """
    def __init__(self, url, post=False, data=None, files=None):
        self.url = urllib.parse.urlparse(url)
        try:
            self.response = self._request(url, post, data, files)
        except requests.exceptions.RequestException:
            raise RemotePageException(
                _("Connecting to the course service failed!"))
        self.response.encoding = "utf-8"
        self.soup = BeautifulSoup(self.response.text, 'html5lib')

    def _request(self, url, post=False, data=None, files=None):
        last_retry = len(settings.EXERCISE_HTTP_RETRIES) - 1
        n = 0
        while n <= last_retry:
            try:
                if post:
                    response = requests.post(url, data=data, files=files,
                        timeout=settings.EXERCISE_HTTP_TIMEOUT)
                else:
                    response = requests.get(url,
                        timeout=settings.EXERCISE_HTTP_TIMEOUT)
                if response.status_code == 200:
                    return response
                elif response.status_code >= 500 and n < last_retry:
                    logger.warning("Retrying: Server error {:d} at {}".format(
                        response.status_code, url))
                else:
                    response.raise_for_status()
            except requests.exceptions.ConnectionError as e:
                if n >= last_retry:
                    raise e
                logger.warning("Retrying: ConnectionError to {}".format(url));
            time.sleep(settings.EXERCISE_HTTP_RETRIES[n])
            n += 1
        logger.error("HTTP request loop ended in unexpected state")
        assert False

    def base_address(self):
        domain = urllib.parse.urlunparse((self.url.scheme, self.url.netloc, '', '', '', ''))
        path = posixpath.dirname(self.url.path)
        return domain, path + '/' if not path or path[-1] != '/' else path

    def meta(self, name):
        if self.soup:
            element = self.soup.find("meta", {"name": name})
            if element:
                return element.get("value",
                    default=element.get("content", default=None))
        return None

    def title(self):
        if self.soup and self.soup.title:
            return self.soup.title.contents
        return ""

    def head(self, search_attribute):
        if self.soup and self.soup.head:
            return "\n".join(str(tag) for tag in
                self.soup.head.find_all(True, search_attribute))
        return ""

    def body(self):
        if self.soup and self.soup.body:
            return self.soup.body.renderContents()
        return ""

    def element_or_body(self, search_attributes):
        if self.soup:
            for attr in search_attributes:
                element = self.soup.find(**attr)
                if element:
                    return element.renderContents()
        return self.body()

    def fix_relative_urls(self):
        domain, path = self.base_address()
        self._fix_relative_urls(domain, path, "img", "src")
        self._fix_relative_urls(domain, path, "script", "src")
        self._fix_relative_urls(domain, path, "link", "href")
        self._fix_relative_urls(domain, path, "a", "href")

    def _fix_relative_urls(self, domain, path, tag_name, attr_name):
        test = re.compile('^(#|\/\/|.+:\/\/|data:.+;)', re.IGNORECASE)
        for element in self.soup.findAll(tag_name, {attr_name:True}):
            value = element[attr_name]
            if value and not test.match(value):
                if value[0] == '/':
                    element[attr_name] = domain + value
                else:
                    element[attr_name] = domain + path + value

    def find_and_replace(self, attr_name, list_of_attributes):
        l = len(list_of_attributes)
        if l == 0:
            return
        i = 0
        for element in self.soup.findAll(True, {attr_name:True}):
            for name,value in list_of_attributes[i].items():
                if name.startswith('?'):
                    if name[1:] in element:
                        element[name[1:]] = value
                else:
                    element[name] = value
            i += 1
            if i >= l:
                return
