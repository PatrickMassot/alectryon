# Copyright © 2019 Clément Pit-Claudel
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

from collections import defaultdict
from contextlib import contextmanager
from functools import wraps
from os import path
import pickle

from dominate import tags

from .core import Text, RichSentence, Goals, Messages
from . import transforms, GENERATOR

_SELF_PATH = path.dirname(path.realpath(__file__))

ADDITIONAL_HEADS = [
    '<meta name="viewport" content="width=device-width, initial-scale=1">'
]

class ASSETS:
    PATH = path.join(_SELF_PATH, "assets")

    ALECTRYON_CSS = ("alectryon.css",)
    ALECTRYON_JS = ("alectryon.js",)

    PYGMENTS_CSS = ("tango_subtle.min.css",)
    DOCUTILS_CSS = ("docutils_basic.css",)

    IBM_PLEX_CDN = '<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/IBM-type/0.5.4/css/ibm-type.min.css" integrity="sha512-sky5cf9Ts6FY1kstGOBHSybfKqdHR41M0Ldb0BjNiv3ifltoQIsg0zIaQ+wwdwgQ0w9vKFW7Js50lxH9vqNSSw==" crossorigin="anonymous" />' # pylint: disable=line-too-long
    FIRA_CODE_CDN = '<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/firacode/5.2.0/fira_code.min.css" integrity="sha512-MbysAYimH1hH2xYzkkMHB6MqxBqfP0megxsCLknbYqHVwXTCg9IqHbk+ZP/vnhO8UEW6PaXAkKe2vQ+SWACxxA==" crossorigin="anonymous" />' # pylint: disable=line-too-long

def b16(i):
    return hex(i)[len("0x"):]

class Gensym():
    def __init__(self, stem):
        self.stem = stem
        self.counters = defaultdict(lambda: -1)

    def __call__(self, prefix):
        self.counters[prefix] += 1
        return self.stem + prefix + b16(self.counters[prefix])

# pylint: disable=line-too-long
HEADER = (
    '<div class="alectryon-banner">'
    'Built with <a href="https://github.com/cpitclaudel/alectryon/">Alectryon</a>, running {}. '
    'Bubbles (<span class="alectryon-bubble"></span>) indicate interactive fragments: hover for details, tap to reveal contents. '
    'Use <kbd>Ctrl+↑</kbd> <kbd>Ctrl+↓</kbd> to navigate, <kbd>Ctrl+🖱️</kbd> to focus. '
    'On Mac, use <kbd>⌘</kbd> instead of <kbd>Ctrl</kbd>.'
    '</div>'
)

def gen_banner(generator, include_version_info=True):
    return HEADER.format(generator.fmt(include_version_info)) if generator else ""

def wrap_classes(*cls):
    return " ".join("alectryon-" + c for c in ("root", *cls))

JS_UNMINIFY_SELECTORS = set()
def deduplicate(selector):
    JS_UNMINIFY_SELECTORS.add(".alectryon-io " + selector)
    def _deduplicate(fn):
        @wraps(fn)
        def _fn(self, *args, **kwargs):
            if self.backrefs is None:
                fn(self, *args, **kwargs)
            else:
                key = (fn.__name__, pickle.dumps((args, kwargs)))
                ref = self.backrefs.get(key)
                if ref is not None:
                    tags.q(ref)
                else:
                    self.backrefs[key] = b16(len(self.backrefs))
                    fn(self, *args, **kwargs)
        return _fn
    return _deduplicate

@contextmanager
def nullctx():
    yield

class HtmlGenerator:
    def __init__(self, highlighter, gensym_stem="", minify=False):
        self.highlight = highlighter
        self.gensym = None if minify else Gensym(gensym_stem + "-" if gensym_stem else "")
        self.minify, self.backrefs = minify, ({} if minify else None)

    @staticmethod
    def gen_label(toggle, cls, *contents):
        if toggle:
            attrs = {"for": toggle["id"]} if toggle["id"] else {}
            return tags.label(*contents, cls=cls, **attrs)
        return tags.span(*contents, cls=cls)

    @deduplicate(".goal-hyps > div")
    def gen_hyp(self, hyp):
        with tags.div():
            tags.var(", ".join(hyp.names))
            with tags.span() if hyp.body else nullctx(): # For alignment
                if hyp.body:
                    with tags.span(cls="hyp-body"):
                        tags.b(":=")
                        tags.span(self.highlight(hyp.body))
                with tags.span(cls="hyp-type"):
                    tags.b(":")
                    tags.span(self.highlight(hyp.type))

    @deduplicate(".goal-hyps")
    def gen_hyps(self, hyps):
        with tags.div(cls="goal-hyps"):
            for hyp in hyps:
                self.gen_hyp(hyp)

    @deduplicate(".goal-conclusion")
    def gen_ccl(self, conclusion):
        tags.div(self.highlight(conclusion), cls="goal-conclusion")

    @deduplicate(".alectryon-goal")
    def gen_goal(self, goal, toggle=None):
        """Serialize a goal to HTML."""
        with tags.blockquote(cls="alectryon-goal"):
            if goal.hypotheses:
                # Chrome doesn't support the ‘gap’ property in flex containers,
                # so properly spacing hypotheses requires giving them margins
                # and giving negative margins to their container.  This breaks
                # when the container is empty, so just omit the hypotheses if
                # there are none.
                self.gen_hyps(goal.hypotheses)
            with self.gen_label(toggle, "goal-separator"):
                tags.hr()
                if goal.name:
                    tags.span(goal.name, cls="goal-name")
            return self.gen_ccl(goal.conclusion)

    def gen_checkbox(self, checked, cls):
        if self.minify:
            return {"id": None}
        # Most RSS readers ignore stylesheets, so add `display: none`
        attrs = {"checked": "checked"} if checked else {}
        return tags.input_(type="checkbox", id=self.gensym("chk"), cls=cls,
                           style="display: none", **attrs)

    @deduplicate(".alectryon-extra-goals")
    def gen_extra_goals(self, goals):
        with tags.div(cls='alectryon-extra-goals'):
            for goal in goals:
                toggle = goal.hypotheses and \
                    self.gen_checkbox(False, "alectryon-extra-goal-toggle")
                self.gen_goal(goal, toggle=toggle)

    @deduplicate(".alectryon-goals")
    def gen_goals(self, goals):
        with tags.div(cls="alectryon-goals"):
            first, *more = goals
            self.gen_goal(first)
            if more:
                self.gen_extra_goals(more)

    def gen_input(self, fr, toggle):
        cls = "alectryon-input" + (" alectryon-failed" if fr.annots.fails else "")
        self.gen_label(toggle, cls, self.highlight(fr.contents))

    @deduplicate(".alectryon-output")
    def gen_output(self, fr):
        # Using <small> improves rendering in RSS feeds
        # The a:show tag is used to initialize the checkbox in minified mode
        cls = "alectryon-output" + (" a:show" if self.minify and fr.annots.unfold else "")
        with tags.small(cls=cls).add(tags.div()): # div has ``position: sticky``
            for output in fr.outputs:
                if isinstance(output, Messages):
                    assert output.messages, "transforms.commit_io_annotations"
                    with tags.div(cls="alectryon-messages"):
                        for message in output.messages:
                            tags.blockquote(self.highlight(message.contents),
                                            cls="alectryon-message")
                if isinstance(output, Goals):
                    assert output.goals, "transforms.commit_io_annotations"
                    self.gen_goals(output.goals)

    @staticmethod
    def gen_whitespace(wsps):
        for wsp in wsps:
            tags.span(wsp, cls="alectryon-wsp")

    def gen_sentence(self, fr):
        if fr.contents is not None:
            self.gen_whitespace(fr.prefixes)
        with tags.span(cls="alectryon-sentence"):
            toggle = fr.outputs and self.gen_checkbox(fr.annots.unfold, "alectryon-toggle")
            if fr.contents is not None:
                self.gen_input(fr, toggle)
            if fr.outputs:
                self.gen_output(fr)
            if fr.contents is not None:
                self.gen_whitespace(fr.suffixes)

    def gen_fragment(self, fr):
        if isinstance(fr, Text):
            tags.span(self.highlight(fr.contents), cls="alectryon-wsp")
        else:
            assert isinstance(fr, RichSentence)
            self.gen_sentence(fr)

    def gen_fragments(self, fragments, classes=()):
        """Serialize a list of `fragments` to HTML."""
        with tags.pre(cls=" ".join(("alectryon-io", "highlight", *classes))) as pre:
            tags.comment(" Generator: {} ".format(GENERATOR))
            fragments = transforms.group_whitespace_with_code(fragments)
            fragments = transforms.commit_io_annotations(fragments)
            for fr in fragments:
                self.gen_fragment(fr)
            return pre

    def gen(self, annotated):
        for fragments in annotated:
            yield self.gen_fragments(fragments)

JS_UNMINIFY = """<script>
    // Resolve backreferences
    document.addEventListener("DOMContentLoaded", function() {
        var references = document.querySelectorAll([$selectors].join(", "));
        document.querySelectorAll('.alectryon-io q').forEach(function (q) {
            q.replaceWith(references[parseInt(q.innerText, 16)].cloneNode(true)) });
    });

    // Add checkboxes
    document.addEventListener("DOMContentLoaded", function() {
        var input = document.createElement("input");
        input.type = "checkbox";
        input.style = "display: none";

        input.className = "alectryon-extra-goal-toggle";
        document.querySelectorAll('.alectryon-io label.goal-separator').forEach(function(lbl, idx) {
            var goal = lbl.parentNode, box = input.cloneNode(true);
            lbl.htmlFor = box.id = "alectryon-hyps-chk" + idx;
            goal.parentNode.insertBefore(box, goal);
        });

        input.className = "alectryon-toggle";
        document.querySelectorAll('.alectryon-io .alectryon-output').forEach(function(div, idx) {
            var box = input.cloneNode(true), lbl = div.previousSibling;
            box.checked = div.classList.contains("a:show");
            if (lbl && lbl.tagName == "LABEL") {
                lbl.htmlFor = box.id = "alectryon-output-chk" + idx;
            }
            div.parentNode.insertBefore(box, lbl || div);
        });
    });
</script>""".replace("$selectors", ','.join(
    '\n           "{}"'.format(sel) for sel in sorted(JS_UNMINIFY_SELECTORS)))
