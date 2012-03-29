"""
**Logic programming** is a model of computation that applies mathematical logic
to problem solving.

### Introduction

Logic programming is declarative, not procedural.  In the procedural programming
paradigm, the programmer specifies data and the algorithms that should be
executed on those data to reach a solution.  In the logic programming paradigm,
the programmer specifies relationships that hold between the data in the form of
facts and rules.  The programmer then specifies a goal, and the computer works
out the implementation details of achieving that goal.

### Specifying relationships

A relation specifies a relationship that holds between some objects.  We denote
relations with the form `pred(obj1, obj2, ...)`, where the name of the relation
is called the *predicate*.

To store relations in our system for use in proving goals, we use *clauses*.  A
clause consists of a *head* relation and some *body* relations.  For example, in
the clause `compatible(John, June) :- common_interests(John, June), lazy(June)`,
we are specifying that John and June are compatible if they have common
interests and June is lazy.  The head of this clause is `compatible(John, June)`
and the body consists of the two relations `common_interests(John, June)` and
`lazy(June)`. We call clauses of this form *rules*, since they specify when a
relation is true.  To specify a relation that is unconditionally true, we use a
clause with no body, called a *fact*: `girl(June)`.

We can use *logic variables* to describe more abstract relations.  Consider the
following clauses:

    female(June)
    likes(June, running)
    likes(John, running)
    similar_hobbies(?x, ?y) :- likes(?x, ?z), likes(?y, ?z)
    compatible(John, ?x) :- female(?x), similar_hobbies(John, ?x)

The last two rules use logic variables.  The second-to-last rule specifies when
two people have similar hobbies (that is, there is something they both like),
and the last rule specifies the people with whom John is compatible.

### Queries

Once we have some clauses, we can specify a goal, and the system will attempt to
satisfy that goal.  In logic programming parlance, we call this *proving* a
goal.  The goal is stated in the form of a relation.

Sometimes our goal requires a yes or no answer.  The system will use the
existing clauses to determine whether the given goal can be satisfied.  For
example, using the five clauses defined above, we might specify the goal
`compatible(John, June)`.  If we try to prove this goal, the result will simply
be "Yes."  If we try to prove the goal `male(June)`, the result will be "No.",
as the system is unable to prove that June is male from the specified clauses.

We can specify much more interesting goals.  For instance, we might specify the
goal `likes(?x, running)`.  Here, we are interested in determining who is
interested in running.  If we attempt to prove this goal, the system will
determine if it can be satisfied, and if so, what values of `?x` satisfy the
goal.  Here, the results will be John and June, since we declared that both of
them like running.  These results that, when substituted for the variables,
satisfy the goal are called the *bindings* of those variables.

For more examples, see the following databases of clauses:

- [Family tree](examples/prolog/family.prolog)
- [Graph traversal](examples/prolog/graph.prolog)
- [Linked lists](examples/prolog/pair.prolog)

These databases can be loaded into the provided [Prolog
interpreter](../prolog.html) for experimentation.

### Implementation

Programming in this model requires some adjustment coming from a procedural
programming background; logic programming appears very mysterious at first.  The
implementation, however, is simple, and relies on three basic concepts:

1. [A uniform database of facts and rules](#database);
2. [Unification of logic variables](#unification);
3. [Automatic backtracking](#backtracking).

Below, we will see how these three concepts are implemented.

### Use

This module provides a library that enables the use of logic programming in
arbitrary Python programs.  For some examples of this, see the following:

- A simple interactive [Prolog interpreter](../prolog.html)
- [Finding members of lists](examples/logic/find_elements.html)
- [Who likes whom](examples/logic/likes.html)

### About

Written by [Daniel Connelly](http://dhconnelly.com).
This implementation is inspired by chapter 11 of "Paradigms of Artificial
Intelligence Programming" by Peter Norvig.
"""

import logging

# <a id="database"></a>
## Uniform database

# The first important idea in our implementation of a logic programming
# system is that of a uniform database.  We store all facts and rules in a
# single data structure, organized so that we can quickly retrieve all the
# clauses that might help prove a goal.  Since our goals are relations,
# while proving a goal we will want to retrieve clauses whose head relations
# match the goal relation.  Thus we will index the database on the predicates
# of the contained clauses' heads.

# The implementation of the database is a single Python dictionary.  Keys are
# the predicates of relations, and values are lists of clauses with identical
# head predicates.

def store(db, clause):
    """Store the clause in the database, indexed on the head's predicate."""
    db.setdefault(clause.head.pred, []).append(clause)

def retrieve(db, pred):
    """Retrieve all clauses with matching head's predicate."""
    return db.setdefault(pred, [])

# It will be useful to store Python functions in the database so that we can
# induce side-effects by proving "relations".

def define_procedure(db, name, proc):
    """Store a Python function in the database with the given name."""
    db[name] = proc


## Data type definitions

# Next we define the types of data represented in our system.  These include:
# 
# - *atoms*, which represent literal data such as numbers and strings;
# - *variables*, which represent undetermined atoms and relations;
# - *relations*, which define relationships between atoms, variables, and
#   other relations;
# - *clauses*, which represent facts and rules stored in the database.

# We want each instance of these types to support a few common operations that
# will be used throughout the system.
#
# - `get_vars`: list all of the variables contained in this instance. For
#   example, if we call `get_vars` on the relation `member(?x, pair(y, ?z))`,
#   we should get back the list `[?x, ?z]`.
# - `rename_vars`: replace variables in this instance using a dictionary that
#   maps old variables to replacement variables.

# ----------------------------------------------------------------------------
class Atom(object):

    """Represents any literal (symbol, number, string, etc)."""
    
    def __init__(self, atom):
        self.atom = atom
        
    def __repr__(self):
        return str(self.atom)

    def __eq__(self, other):
        return isinstance(other, Atom) and other.atom == self.atom

    # These don't need to do anything for Atoms, since they don't contain Vars.
    def rename_vars(self, replacements): return self
    def get_vars(self): return []


# ----------------------------------------------------------------------------
class Var(object):

    """Represents a logic variable."""

    counter = 0 # for generating unused variables
    @staticmethod
    def get_unused_var():
        """Get a new, unused Var."""
        # While proving goals we will sometimes want to create unused, temporary
        # variables, so we do so by keeping a count of how many have been
        # created and use it to name new ones.
        v = Var('var%d' % Var.counter)
        Var.counter += 1
        return v
    
    def __init__(self, var):
        self.var = var
        
    def __repr__(self):
        return '?%s' % str(self.var)

    def __eq__(self, other):
        return isinstance(other, Var) and other.var == self.var

    def __hash__(self):
        return hash(self.var)

    # As mentioned above in the section on "Queries", variables will be bound
    # to other values.  These bindings will be tracked through dictionaries.

    def lookup(self, bindings):
        """
        Find the term that self is bound to in bindings.

        Tries to find a non-Var binding to return by searching transitively
        through the bindings dictionary.
        """
        
        binding = bindings.get(self)

        # While looking up the binding for self, we must detect:
        # 
        # 1. That we are looking up the binding of a Var (otherwise meaningless)
        # 2. That we stop before reaching None, in the case that there is no
        #    terminal Atom in a transitive binding
        # 3. That we don't go in a circle (eg, x->y and y->x)

        encountered = [self, binding]
        while (isinstance(binding, Var)
               and binding in bindings
               and bindings[binding] not in encountered):
            binding = bindings.get(binding)
            encountered.append(binding)

        # If the next binding leads to a relation, expand it.
        if isinstance(binding, Relation):
            return binding.bind_vars(bindings)

        return binding
    
    def rename_vars(self, replacements):
        """Rename self with its value in replacements if it appears as a key."""
        return replacements.get(self, self)

    def get_vars(self):
        """Return a list containing this var."""
        return [self]


# ----------------------------------------------------------------------------
class Relation(object):

    """A relationship (specified by a predicate) that holds between terms."""
    
    def __init__(self, pred, args):
        self.pred = pred
        self.args = args
        
    def __repr__(self):
        return '%s(%s)' % (self.pred, ', '.join(map(str, self.args)))

    def __eq__(self, other):
        return (isinstance(other, Relation)
                and self.pred == other.pred
                and list(self.args) == list(other.args))

    def bind_vars(self, bindings):
        """Replace each Var in this relation with its bound term."""
        bound = []
        for arg in self.args:
            bound.append(arg.lookup(bindings) if arg in bindings else arg)
        return Relation(self.pred, bound)

    def rename_vars(self, replacements):
        """Recursively rename each Var in this relation."""
        renamed = []
        for arg in self.args:
            renamed.append(arg.rename_vars(replacements))
        return Relation(self.pred, renamed)

    def get_vars(self):
        """Return all Vars in this relation."""
        vars = []
        for arg in self.args:
            vars.extend(v for v in arg.get_vars() if v not in vars)
        return vars


# ----------------------------------------------------------------------------
class Clause(object):
    
    """A clause with a head relation and some body relations."""
    
    def __init__(self, head, body=None):
        self.head = head
        self.body = body or []

    def __repr__(self):
        if self.body:
            return '%s :- %s' % (self.head, ', '.join(map(str, self.body)))
        return str(self.head)

    def __eq__(self, other):
        return (isinstance(other, Clause)
                and self.head == other.head
                and list(self.body) == list(other.body))

    def bind_vars(self, bindings):
        """Replace all Vars in this clause with their bound values."""
        head = self.head.bind_vars(bindings)
        body = [r.bind_vars(bindings) for r in self.body]
        return Clause(head, body)

    def rename_vars(self, replacements):
        """Recursively rename each Var in this Clause."""
        renamed_head = self.head.rename_vars(replacements)
        renamed_body = []
        for term in self.body:
            renamed_body.append(term.rename_vars(replacements))
        return Clause(renamed_head, renamed_body)

    def recursive_rename(self):
        """Replace each var in self with an unused one."""
        renames = {v: Var.get_unused_var() for v in self.get_vars()}
        logging.debug('Renamed vars: %s' % renames)
        return self.rename_vars(renames)

    def get_vars(self):
        """Return a list of all Vars in this Clause."""
        vars = self.head.get_vars()
        for rel in self.body:
            vars.extend(v for v in rel.get_vars() if v not in vars)
        return vars


# <a id="unification"></a>
## Unification of logic variables

# TODO description

def unify(x, y, bindings):
    """Unify x and y, if possible.  Returns updated bindings or None."""
    logging.debug('Unify %s and %s (bindings=%s)' % (x, y, bindings))

    if bindings == False:
        return False

    # Make a copy of bindings so we can backtrack if necessary.
    bindings = dict(bindings)

    # When x and y are equal (the same Var or Atom), there's nothing to do.
    if x == y:
        return bindings

    # Unify Vars and anything
    if isinstance(x, Var):
        # If x (or y) is already bound to something, dereference and try again.
        if x in bindings:
            return unify(bindings[x], y, bindings)
        if y in bindings:
            return unify(x, bindings[y], bindings)

        # Otherwise, bind x to y.
        bindings[x] = y
        return bindings
    if isinstance(y, Var):
        return unify(y, x, bindings)

    # Unify Relations with Relations
    if isinstance(x, Relation) and isinstance(y, Relation):
        # Two relations must have the same predicate and arity to unify.
        if x.pred != y.pred:
            return False
        if len(x.args) != len(y.args):
            return False

        # Unify corresponding terms in the relations.
        for i, xi in enumerate(x.args):
            yi = y.args[i]
            bindings = unify(xi, yi, bindings)
            if bindings == False:
                return False

        return bindings

    # Unify Clauses with Clauses
    if isinstance(x, Clause) and isinstance(y, Clause):
        # Clause bodies must have the same length to unify.
        if len(x.body) != len(y.body):
            return False

        # Unify head term and body terms.
        bindings = unify(x.head, y.head, bindings)
        if bindings == False:
            return False
        for i, xi in enumerate(x.body):
            yi = y.body[i]
            bindings = unify(xi, yi, bindings)
            if bindings == False:
                return False
        return bindings

    # Nothing else can unify.
    return False


# <a id="backtracking"></a>
## Automatic Backtracking

# TODO

def prove_all(goals, bindings, db):
    """Prove all the goals with the given bindings and rule database."""
    if bindings == False:
        return False
    if not goals:
        return bindings
    logging.debug('Proving goals: %s (bindings=%s)' % (goals, bindings))
    return prove(goals[0], bindings, db, goals[1:])


def prove(goal, bindings, db, remaining=None):
    """
    Try to prove goal using the given bindings and clause database.

    If successful, returns the extended bindings that satisfy goal.
    Otherwise, returns False.
    """

    if bindings == False:
        return False
    
    logging.debug('Prove %s (bindings=%s)' % (goal, bindings))
    remaining = remaining or []
    
    # Find the clauses in the database that might help us prove goal.
    query = db.get(goal.pred)
    if not query:
        return False
    
    if not isinstance(query, list):
        # If the retrieved data from the database isn't a list of clauses,
        # it must be a primitive.
        return query(goal.args, bindings, db, remaining)

    logging.debug('Candidate clauses: %s' % query)
    for clause in query:
        logging.debug('Trying candidate clause %s for goal %s' % (clause, goal))
        
        # First, rename the variables in clause so they don't collide with
        # those in goal.
        renamed = clause.recursive_rename()

        # Next, we try to unify goal with the head of the candidate clause.
        # If unification is possible, then the candidate clause might either be
        # a rule that can prove goal or a fact that states goal is already true.
        unified = unify(goal, renamed.head, bindings)
        if unified == False:
            continue

        # Make sure the candidate clause doesn't lead to an infinite loop
        # by checking to see if its head is in its body.
        renamed = renamed.bind_vars(unified)
        if renamed.head in renamed.body:
            continue

        # We need to prove the subgoals of the candidate clause before
        # using it to prove goal.
        extended = prove_all(renamed.body + remaining, unified, db)
        
        # If we can't prove all the subgoals of this clause, move on.
        if extended == False:
            continue

        # Return the bindings that satisfied the goal.
        return extended

    logging.debug('Failed to prove %s' % goal)
    return False
    

def display_bindings(vars, bindings, db, remaining):
    """Primitive procedure for displaying bindings to the user."""
    if not vars:
        print 'Yes.'
    for var in vars:
        print var, ':', var.lookup(bindings)
    if raw_input('Continue? ').strip().lower() in ('yes', 'y'):
        return False
    return prove_all(remaining, bindings, db)


## Helper functions for external interface

def prolog_prove(goals, db):
    """Prove each goal in goals using the rules and facts in db."""
    if goals:
        vars = []
        for goal in goals:
            vars.extend(goal.get_vars())
        db['display_bindings'] = display_bindings
        prove_all(goals + [Relation('display_bindings', vars)], {}, db)
    print 'No.'
