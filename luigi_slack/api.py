import os
import logging
import inspect
from contextlib import contextmanager
from collections import defaultdict
import luigi
from luigi_slack.slack_api import SlackAPI, SlackBotConf
from luigi_slack.events import SUCCESS, MISSING, FAILURE, START, PROCESSING_TIME
from luigi_slack.events import event_label

class SlackBot(object):

    def __init__(self,
                 token,
                 channels=[],
                 events=[FAILURE],
                 max_events=5,
                 bot_conf=SlackBotConf()):
        if not isinstance(events, list):
            raise ValueError('events must be a list, {} given'.format(type(events)))
        if not channels:
            logging.info('channels=[], notifications are not sent')
        self.events = events
        self.client = SlackAPI(token, bot_conf)
        self.channels = channels
        self.max_events = 5
        self.event_queue = defaultdict(list)    

    def send_notification(self):
        message = self._format_message()
        post_to = self.channels
        self.client.bulk_message(message, post_to)
        return True

    def set_handlers(self):
        for event in self.events:
            if event not in _event_handlers:
                raise ValueError("{} is not a valid event type".format(event))
            handler = _event_handlers[event]['luigi_handler']
            function = _event_handlers[event]['function']
            luigi.Task.event_handler(handler)(function)
        return True

    def _success(self, task):
        task = str(task)
        self.event_queue[FAILURE] = [fail for fail in self.event_queue[FAILURE] if task != fail['task']]
        self.event_queue[MISSING] = [miss for miss in self.event_queue[MISSING] if task != miss]
        self.event_queue[START] = [start for start in self.event_queue[START] if task != start]

    def _failure(self, task, exception):
        task = str(task)
        failure = {'task': task, 'exception': str(exception)}
        self.event_queue[FAILURE].append(failure)

    def _missing(self, task):
        task = str(task)
        self.event_queue[MISSING].append(task)

    def _start(self, task):
        task = str(task)
        self.event_queue[START].append(task)

    def _processing_time(self, task):
        raise NotImplementedError

    def _format_message(self):
        job = os.path.basename(inspect.stack()[-1][1])
        messages = ["Status report for {}".format(job)]
        messages = self._message_append_events(messages)
        if len(messages) == 1:
            messages.append("Job ran successfully!")
        text = "\n".join(messages)
        return text

    def _message_append_events(self, messages):
        for event_type in self.events:
            if event_type in self.event_queue:
                label = event_label(event_type)
                messages.append(label)
                if len(self.event_queue[event_type]) > self.max_events:
                    messages.append("More than {} events of type {}. Please check logs.".format(self.max_events, label))
                else: 
                    for event in self.event_queue[event_type]:
                        try:
                            messages.append("Task: {}; Exception: {}".format(event['task'], event['exception']))
                        except TypeError:
                            messages.append(event)
        return messages


_event_handlers = {
    SUCCESS: {
        'luigi_handler': luigi.Event.SUCCESS,
        'function': SlackBot._success
    },
    FAILURE: {
        'luigi_handler': luigi.Event.FAILURE,
        'function': SlackBot._failure
    },
    START: {
        'luigi_handler': luigi.Event.START,
        'function': SlackBot._start
    },
    MISSING: {
        'luigi_handler': luigi.Event.DEPENDENCY_MISSING,
        'function': SlackBot._missing
    },
    PROCESSING_TIME: {
        'luigi_handler': luigi.Event.PROCESSING_TIME,
        'function': SlackBot._processing_time
    }
}


@contextmanager
def notify(slacker):
    slacker.set_handlers()
    yield
    slacker.send_notification()
