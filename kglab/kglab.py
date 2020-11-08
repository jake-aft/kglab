#!/usr/bin/env python
# encoding: utf-8

from rdflib import plugin
from rdflib.serializer import Serializer
# NB: while `plugin` isn't used directly, loading it
# here causes it to become registered within `rdflib`
import dateutil.parser as dup
import pathlib
import json
import rdflib as rdf
import rdflib.namespace


######################################################################
## KG class definition

class KnowledgeGraph:
    DEFAULT_NAMESPACES = {
        "dc":	"https://purl.org/dc/terms/",
        "dct":	"https://purl.org/dc/dcmitype/",
        "owl":	"https://www.w3.org/2002/07/owl#",
        "rdf":	"http://www.w3.org/1999/02/22-rdf-syntax-ns#",
        "rdfs":	"http://www.w3.org/2000/01/rdf-schema#",
        "skos":	"https://www.w3.org/2004/02/skos/core#",
        "xsd":	"http://www.w3.org/2001/XMLSchema#",
        }


    def __init__ (self, name="KGlab", base_uri=None, language="en", namespaces={}):
            self._g = rdf.Graph()
        self.label_dict = {}

        self.name = name
        self.base_uri = base_uri
        self.language = language

        self._nm = rdflib.namespace.NamespaceManager(self._g)
        self._ns = {}
        self.merge_ns({ **self.DEFAULT_NAMESPACES, **namespaces })


    ######################################################################
    ## namespace management

    def merge_ns (self, ns_set):
        for prefix, uri in ns_set.items():
            self.add_ns(prefix, uri)


    def add_ns (self, prefix, uri):
        self._ns[prefix] = rdf.Namespace(uri)
        self._nm.bind(prefix, self._ns[prefix])


    def get_ns (self, prefix):
        return self._ns[prefix]


    def get_context (self):
        """return a context needed for JSON-LD serialization"""
        context = {
            "@language": self.language,
            }

        if self.base_uri:
            context["@vocab"] = self.base_uri

        for prefix, uri in self._ns.items():
            if uri != self.base_uri:
                context[prefix] = uri

        return context


    ######################################################################
    ## graph building

    def add (self, s, p, o):
        self._g.add((s, p, o,))


    @classmethod
    def type_date (cls, date, tz):
        """input `date` should be interpretable as having a local timezone"""
        date_tz = dup.parse(date, tzinfos=tz)
        return rdf.Literal(date_tz, datatype=rdf.XSD.dateTime)


    ######################################################################
    ## queries

    def query (self, query):
        for row in self._g.query(query):
            yield row


    ######################################################################
    ## serialization

    def load_json (self, path, encoding="utf-8"):
        with open(path, "r", encoding=encoding) as f:
            data = json.load(f)
            self._g.parse(data=json.dumps(data), format="json-ld", encoding=encoding)


    def save_json (self, path, encoding="utf-8"):
        data = self._g.serialize(
            format = "json-ld",
            context = self.get_context(),
            indent = 2,
            encoding = encoding
            )

        with open(path, "wb") as f:
            f.write(data)


    def load_ttl (self, path, encoding="utf-8", format="n3"):
        if isinstance(path, pathlib.Path):
            filename = path.as_posix()
        else:
            filename = path

        self._g.parse(filename, format="n3", encoding=encoding)


    def save_ttl (self, path, encoding="utf-8", format="n3"):
        if isinstance(path, pathlib.Path):
            filename = path.as_posix()
        else:
            filename = path

        self._g.serialize(destination=filename, format=format, encoding=encoding)


    ######################################################################
    ## SKOS inference
    ## adapted from `skosify` https://github.com/NatLibFi/Skosify
    ## it wasn't being updated regularly, but may be integrated again

    def infer_skos_related (self):
        """Make sure that skos:related is stated in both directions (S23)."""
        _skos = self.get_ns("skos")

        for s, o in self._g.subject_objects(_skos.related):
            self._g.add((o, _skos.related, s))


    def infer_skos_topConcept (self):
        """Infer skos:topConceptOf/skos:hasTopConcept (S8) and skos:inScheme (S7)."""
        _skos = self.get_ns("skos")

        for s, o in self._g.subject_objects(_skos.hasTopConcept):
            self._g.add((o, _skos.topConceptOf, s))

        for s, o in self._g.subject_objects(_skos.topConceptOf):
            self._g.add((o, _skos.hasTopConcept, s))

        for s, o in self._g.subject_objects(_skos.topConceptOf):
            self._g.add((s, _skos.inScheme, o))


    def infer_skos_hierarchical (self, narrower=True):
        """Infer skos:broader/skos:narrower (S25) but only keep skos:narrower on request.
        :param bool narrower: If set to False, skos:narrower will not be added,
        but rather removed.
        """
        _skos = self.get_ns("skos")

        if narrower:
            for s, o in self._g.subject_objects(_skos.broader):
                self._g.add((o, _skos.narrower, s))

        for s, o in self._g.subject_objects(_skos.narrower):
            self._g.add((o, _skos.broader, s))

            if not narrower:
                self._g.remove((s, _skos.narrower, o))


    def infer_skos_transitive (self, narrower=True):
        """Perform transitive closure inference (S22, S24)."""
        _skos = self.get_ns("skos")

        for conc in self._g.subjects(self.get_ns("rdf").type, _skos.Concept):
            for bt in self._g.transitive_objects(conc, _skos.broader):
                if bt == conc:
                    continue

                self._g.add((conc, _skos.broaderTransitive, bt))

                if narrower:
                    self._g.add((bt, _skos.narrowerTransitive, conc))


    def infer_skos_symmetric_mappings (self, related=True):
        """Ensure that the symmetric mapping properties (skos:relatedMatch,
        skos:closeMatch and skos:exactMatch) are stated in both directions (S44).
        :param bool related: Add the skos:related super-property for all
            skos:relatedMatch relations (S41).
        """
        _skos = self.get_ns("skos")

        for s, o in self._g.subject_objects(_skos.relatedMatch):
            self._g.add((o, _skos.relatedMatch, s))

            if related:
                self._g.add((s, _skos.related, o))
                self._g.add((o, _skos.related, s))

        for s, o in self._g.subject_objects(_skos.closeMatch):
            self._g.add((o, _skos.closeMatch, s))

        for s, o in self._g.subject_objects(_skos.exactMatch):
            self._g.add((o, _skos.exactMatch, s))


    def infer_skos_hierarchical_mappings (self, narrower=True):
        """Infer skos:broadMatch/skos:narrowMatch (S43) and add the super-properties
        skos:broader/skos:narrower (S41).
        :param bool narrower: If set to False, skos:narrowMatch will not be added,
            but rather removed.
        """
        _skos = self.get_ns("skos")

        for s, o in self._g.subject_objects(_skos.broadMatch):
            self._g.add((s, _skos.broader, o))

            if narrower:
                self._g.add((o, _skos.narrowMatch, s))
                self._g.add((o, _skos.narrower, s))

        for s, o in self._g.subject_objects(_skos.narrowMatch):
            self._g.add((o, _skos.broadMatch, s))
            self._g.add((o, _skos.broader, s))

            if narrower:
                self._g.add((s, _skos.narrower, o))
            else:
                self._g.remove((s, _skos.narrowMatch, o))


    def infer_rdfs_classes (self):
        """Perform RDFS subclass inference.
        Mark all resources with a subclass type with the upper class."""
        _rdfs = self.get_ns("rdfs")

        # find out the subclass mappings
        upperclasses = {}  # key: class val: set([superclass1, superclass2..])

        for s, o in self._g.subject_objects(_rdfs.subClassOf):
            upperclasses.setdefault(s, set())

            for uc in self._g.transitive_objects(s, _rdfs.subClassOf):
                if uc != s:
                    upperclasses[s].add(uc)

        # set the superclass type information for subclass instances
        for s, ucs in upperclasses.items():
            #logging.debug("setting superclass types: %s -> %s", s, str(ucs))
            for res in self._g.subjects(self.get_ns("rdf").type, s):
                for uc in ucs:
                    self._g.add((res, self.get_ns("rdf").type, uc))


    def infer_rdfs_properties (self):
        """Perform RDFS subproperty inference.
        Add superproperties where subproperties have been used."""
        _rdfs = self.get_ns("rdfs")

        # find out the subproperty mappings
        superprops = {}  # key: property val: set([superprop1, superprop2..])

        for s, o in self._g.subject_objects(_rdfs.subPropertyOf):
            superprops.setdefault(s, set())

            for sp in self._g.transitive_objects(s, _rdfs.subPropertyOf):
                if sp != s:
                    superprops[s].add(sp)

        # add the superproperty relationships
        for p, sps in superprops.items():
            #logging.debug("setting superproperties: %s -> %s", p, str(sps))
            for s, o in self._g.subject_objects(p):
                for sp in sps:
                    self._g.add((s, sp, o))


