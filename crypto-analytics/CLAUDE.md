# SOLID Principles Specification

## S - Single Responsibility Principle (SRP)

**Definition:** A module should be responsible to one, and only one, actor.

**Explanation:** A module should have one, and only one, reason to change. An actor is the source of change - a person, role, or group that requires the change. When a module serves multiple actors with different needs, it violates SRP. The principle is about people and roles, not about functions. Different aspects of a system that change for different reasons should be separated into distinct modules to minimize the impact of changes.

## O - Open/Closed Principle (OCP)

**Definition:** Software entities should be open for extension, but closed for modification.

**Explanation:** The behavior of a software module should be extendable without modifying its source code. This is achieved through abstraction and polymorphism, where new functionality is added by creating new code rather than changing existing, working code. The goal is to design modules that never change once they are implemented, while still allowing the system's behavior to be extended through new implementations of abstractions.

## L - Liskov Substitution Principle (LSP)

**Definition:** Objects of a superclass should be replaceable with objects of its subclasses without breaking the application.

**Explanation:** Subtypes must be behaviorally substitutable for their base types. This goes beyond mere syntactic compatibility to require semantic interoperability. A subtype must honor the implicit and explicit contracts of its supertype: it cannot strengthen preconditions, weaken postconditions, or violate invariants established by the base type. The principle ensures that inheritance hierarchies represent true "is-a" relationships with consistent behavior.

## I - Interface Segregation Principle (ISP)

**Definition:** Clients should not be forced to depend upon interfaces they do not use.

**Explanation:** No client should be forced to implement methods it doesn't use. Rather than one general-purpose interface, multiple specific interfaces are preferred. Interfaces should be designed from the client's perspective, not from the implementation's perspective. When a client depends on methods it doesn't need, it creates unnecessary coupling and increases the impact of changes to the interface.

## D - Dependency Inversion Principle (DIP)

**Definition:** High-level modules should not depend on low-level modules. Both should depend on abstractions.

**Explanation:** Dependencies should flow toward abstractions, not concretions. High-level policy should not depend on low-level details; instead, both should depend on abstractions. The abstractions should not depend on details - details should depend on abstractions. This inverts the traditional dependency relationship where high-level modules depend on low-level modules, creating a more flexible architecture where concrete implementations can be changed without affecting business rules.
