from __future__ import annotations
import haiku as hk
import jax.numpy as jnp
import networkx as nx
from haiku._src import base
from uuid import uuid4
from jax.scipy.integrate import trapezoid
from abc import ABC
from simpleeval import simple_eval


class SpectralModel:
    """
    This class is supposed to handle the composition of models through basic
    operations, and allows tracking of the operation graph and individual parameters.
    """

    raw_graph: nx.DiGraph
    graph: nx.DiGraph
    labels: dict[str, str]
    n_parameters: int

    def __init__(self, internal_graph, labels):
        self.raw_graph = internal_graph
        self.labels = labels
        self.graph = self.build_namespace()

        self.n_parameters = hk.data_structures.tree_size(self.params)

    @classmethod
    def from_string(cls, string: str) -> SpectralModel:
        """
        This constructor enable to build a model from a string. The string should be a valid python expression, with
        the following constraints :

        * The model components should be defined in the jaxspec.model.list module
        * The model components should be separated by a * or a + (no convolution yet)
        * The model components should be written with their parameters in parentheses

        Parameters:
            string : The string to parse

        Examples:
            An absorbed model with a powerlaw and a blackbody:

            >>> model = SpectralModel.from_string("Tbabs()*(Powerlaw() + Blackbody())")
        """

        from .list import model_components

        return simple_eval(string, functions=model_components)

    def to_string(self) -> str:
        """
        This method return the string representation of the model.

        Examples:
            Build a model from a string and convert it back to a string:

            >>> model = SpectralModel.from_string("Tbabs()*(Powerlaw() + Blackbody())")
            >>> model.to_string()
            "Tbabs()*(Powerlaw() + Blackbody())"
        """

        return str(self)

    def __str__(self) -> SpectralModel:
        def build_expression(node_id):
            node = self.graph.nodes[node_id]
            if node["type"] == "component":
                string = node["component"].__name__

                if node["kwargs"]:
                    kwargs = ", ".join([f"{k}={v}" for k, v in node["kwargs"].items()])
                    string += f"({kwargs})"
                else:
                    string += "()"
                return string

            elif node["type"] == "operation":
                predecessors = list(self.graph.predecessors(node_id))
                operands = [build_expression(pred) for pred in predecessors]
                operation = node["operation_label"]
                return f"({f' {operation} '.join(operands)})"
            elif node["type"] == "out":
                predecessors = list(self.graph.predecessors(node_id))
                return build_expression(predecessors[0])

        return build_expression("out")[1:-1]

    @property
    def transformed_func_photon(self):
        return hk.without_apply_rng(hk.transform(lambda e_low, e_high: self.flux(e_low, e_high)))

    @property
    def transformed_func_energy(self):
        return hk.without_apply_rng(hk.transform(lambda e_low, e_high: self.flux(e_low, e_high, energy_flux=True)))

    @property
    def params(self):
        return self.transformed_func_photon.init(None, jnp.ones(10), jnp.ones(10))

    def photon_flux(self, *args, **kwargs):
        r"""
        Compute the expected counts between $E_\min$ and $E_\max$ by integrating the model.

        $$ \Phi_{\text{photon}}\left(E_\min, ~E_\max\right) =
        \int _{E_\min}^{E_\max}\text{d}E ~ \mathcal{M}\left( E \right)
        \quad \left[\frac{\text{photons}}{\text{cm}^2\text{s}}\right]$$

        !!! info
            This method is internally used in the inference process and should not be used directly. See
            [`photon_flux`](/references/results/#jaxspec.analysis.results.ChainResult.photon_flux) to compute
            the photon flux associated with a set of fitted parameters in a
            [`ChainResult`](/references/results/#jaxspec.analysis.results.ChainResult)
            instead.
        """
        return self.transformed_func_photon.apply(*args, **kwargs)

    def energy_flux(self, *args, **kwargs):
        r"""
        Compute the expected energy flux between $E_\min$ and $E_\max$ by integrating the model.

        $$ \Phi_{\text{energy}}\left(E_\min, ~E_\max\right) =
        \int _{E_\min}^{E_\max}\text{d}E ~ E ~ \mathcal{M}\left( E \right)
        \quad \left[\frac{\text{keV}}{\text{cm}^2\text{s}}\right]$$

        !!! info
            This method is internally used in the inference process and should not be used directly. See
            [`energy_flux`](/references/results/#jaxspec.analysis.results.ChainResult.energy_flux) to compute
            the energy flux associated with a set of fitted parameters in a
            [`ChainResult`](/references/results/#jaxspec.analysis.results.ChainResult)
            instead.
        """
        return self.transformed_func_energy.apply(*args, **kwargs)

    def build_namespace(self):
        """
        This method build a namespace for the model components, to avoid name collision
        """

        name_space = []
        new_graph = self.raw_graph.copy()

        for node_id in nx.dag.topological_sort(new_graph):
            node = new_graph.nodes[node_id]

            if node and node["type"] == "component":
                name_space.append(node["name"])
                n = name_space.count(node["name"])
                nx.set_node_attributes(new_graph, {node_id: name_space[-1] + f"_{n}"}, "name")

        return new_graph

    def flux(self, e_low, e_high, energy_flux=False):
        """
        This method return the expected counts between e_low and e_high by integrating the model.
        It contains most of the "usine à gaz" which makes jaxspec works.
        It evaluates the graph of operations and returns the result.
        It should be transformed using haiku.
        """

        energies = jnp.hstack((e_low, e_high[-1]))
        energies_to_integrate = jnp.stack((e_low, e_high))

        fine_structures_flux = jnp.zeros_like(e_low)
        runtime_modules = {}
        continuum = {}

        # Iterate through the graph in topological order and
        # compute the continuum contribution for each component

        for node_id in nx.dag.topological_sort(self.graph):
            node = self.graph.nodes[node_id]

            # Instantiate the haiku modules
            if node and node["type"] == "component":
                runtime_modules[node_id] = node["component"](name=node["name"], **node["kwargs"])
                continuum[node_id] = runtime_modules[node_id].continuum(energies)

            elif node and node["type"] == "operation":
                component_1 = list(self.graph.in_edges(node_id))[0][0]
                component_2 = list(self.graph.in_edges(node_id))[1][0]
                continuum[node_id] = node["function"](continuum[component_1], continuum[component_2])

        flux_1D = continuum[list(self.graph.in_edges("out"))[0][0]]
        flux = jnp.stack((flux_1D[:-1], flux_1D[1:]))

        if energy_flux:
            continuum_flux = trapezoid(
                flux * energies_to_integrate**2,
                x=jnp.log(energies_to_integrate),
                axis=0,
            )

        else:
            continuum_flux = trapezoid(flux * energies_to_integrate, x=jnp.log(energies_to_integrate), axis=0)

        # Iterate from the root nodes to the output node and
        # compute the fine structure contribution for each component

        root_nodes = [
            node_id
            for node_id, in_degree in self.graph.in_degree(self.graph.nodes)
            if in_degree == 0 and self.graph.nodes[node_id].get("component_type") == "additive"
        ]

        for root_node_id in root_nodes:
            path = nx.shortest_path(self.graph, source=root_node_id, target="out")
            nodes_id_in_path = [node_id for node_id in path]

            flux_from_component, mean_energy = runtime_modules[root_node_id].emission_lines(e_low, e_high)

            multiplicative_nodes = []

            # Search all multiplicative components connected to this node
            # and apply them at mean energy
            for node_id in nodes_id_in_path[::-1]:
                multiplicative_nodes.extend([node_id for node_id in self.find_multiplicative_components(node_id)])

            for mul_node in multiplicative_nodes:
                flux_from_component *= runtime_modules[mul_node].continuum(mean_energy)

            if energy_flux:
                fine_structures_flux += trapezoid(
                    flux_from_component * energies_to_integrate,
                    x=jnp.log(energies_to_integrate),
                    axis=0,
                )

            else:
                fine_structures_flux += flux_from_component

        return continuum_flux + fine_structures_flux

    def find_multiplicative_components(self, node_id):
        """
        Recursively finds all the multiplicative components connected to the node with the given ID.
        """
        node = self.graph.nodes[node_id]
        multiplicative_nodes = []

        if node.get("operation_type") == "mul":
            # Recursively find all the multiplicative components using the predecessors
            predecessors = self.graph.pred[node_id]
            for node_id in predecessors:
                if self.graph.nodes[node_id].get("component_type") == "multiplicative":
                    multiplicative_nodes.append(node_id)
                elif self.graph.nodes[node_id].get("operation_type") == "mul":
                    multiplicative_nodes.extend(self.find_multiplicative_components(node_id))

        return multiplicative_nodes

    def __call__(self, pars, e_low, e_high):
        return self.photon_flux(pars, e_low, e_high)

    @classmethod
    def from_component(cls, component, **kwargs) -> SpectralModel:
        """
        Build a model from a single component
        """

        graph = nx.DiGraph()

        # Add the component node
        # Random static node id to keep it trackable in the graph
        node_id = str(uuid4())

        if component.type == "additive":

            def lam_func(e):
                return component().continuum(e) + component().emission_lines(e, e + 1)[0]

        elif component.type == "multiplicative":

            def lam_func(e):
                return component().continuum(e)

        else:

            def lam_func(e):
                return print("Some components are not working at this stage")

        node_properties = {
            "type": "component",
            "component_type": component.type,
            "name": component.__name__.lower(),
            "component": component,
            "params": hk.transform(lam_func).init(None, jnp.ones(1)),
            "fine_structure": False,
            "kwargs": kwargs,
            "depth": 0,
        }

        graph.add_node(node_id, **node_properties)

        # Add the output node
        labels = {node_id: component.__name__.lower(), "out": "out"}

        graph.add_node("out", type="out", depth=1)
        graph.add_edge(node_id, "out")

        return cls(graph, labels)

    def compose(self, other: SpectralModel, operation=None, function=None, name=None) -> SpectralModel:
        """
        This function operate a composition between the operation graph of two models
        1) It fuses the two graphs using which joins at the 'out' nodes
        2) It relabels the 'out' node with a unique identifier and labels it with the operation
        3) It links the operation to a new 'out' node
        """

        # Compose the two graphs with their output as common node
        # and add the operation node by overwriting the 'out' node
        node_id = str(uuid4())
        graph = nx.relabel_nodes(nx.compose(self.raw_graph, other.raw_graph), {"out": node_id})
        nx.set_node_attributes(graph, {node_id: "operation"}, "type")
        nx.set_node_attributes(graph, {node_id: operation}, "operation_type")
        nx.set_node_attributes(graph, {node_id: function}, "function")
        nx.set_node_attributes(graph, {node_id: name}, "operation_label")

        # Merge label dictionaries
        labels = self.labels | other.labels
        labels[node_id] = operation

        # Now add the output node and link it to the operation node
        graph.add_node("out", type="out")
        graph.add_edge(node_id, "out")

        # Compute the new depth of each node
        longest_path = nx.dag_longest_path_length(graph)

        for node in graph.nodes:
            nx.set_node_attributes(
                graph,
                {node: longest_path - nx.shortest_path_length(graph, node, "out")},
                "depth",
            )

        return SpectralModel(graph, labels)

    def __add__(self, other: SpectralModel) -> SpectralModel:
        return self.compose(other, operation="add", function=lambda x, y: x + y, name="+")

    def __mul__(self, other: SpectralModel) -> SpectralModel:
        return self.compose(other, operation="mul", function=lambda x, y: x * y, name=r"*")

    def export_to_mermaid(self, file=None):
        mermaid_code = "graph LR\n"  # LR = left to right

        # Add nodes
        for node, attributes in self.graph.nodes(data=True):
            if attributes["type"] == "component":
                name, number = attributes["name"].split("_")
                mermaid_code += f'    {node}("{name.capitalize()} ({number})")\n'

            if attributes["type"] == "operation":
                if attributes["operation_type"] == "add":
                    mermaid_code += f"    {node}{{+}}\n"

                if attributes["operation_type"] == "mul":
                    mermaid_code += f"    {node}{{x}}\n"

            if attributes["type"] == "out":
                mermaid_code += f'    {node}("Output")\n'

        # Draw connexion between nodes
        for source, target in self.graph.edges():
            mermaid_code += f"    {source} --> {target}\n"

        if file is None:
            return mermaid_code
        else:
            with open(file, "w") as f:
                f.write(mermaid_code)

    def _repr_html_(self):
        return "``` mermaid \n" + self.export_to_mermaid() + "\n```"

    def plot(self, figsize=(8, 8)):
        import matplotlib.pyplot as plt

        plt.figure(figsize=figsize)

        pos = nx.multipartite_layout(self.graph, subset_key="depth", scale=1)

        nodes_out = [x for x, y in self.graph.nodes(data=True) if y["type"] == "out"]
        nx.draw_networkx_nodes(self.graph, pos, nodelist=nodes_out, node_color="tab:green")
        nx.draw_networkx_edges(self.graph, pos, width=1.0)

        nx.draw_networkx_labels(
            self.graph,
            pos,
            labels=nx.get_node_attributes(self.graph, "name"),
            font_size=12,
            font_color="black",
            bbox={"fc": "tab:red", "boxstyle": "round", "pad": 0.3},
        )
        nx.draw_networkx_labels(
            self.graph,
            pos,
            labels=nx.get_node_attributes(self.graph, "operation_label"),
            font_size=12,
            font_color="black",
            bbox={"fc": "tab:blue", "boxstyle": "circle", "pad": 0.3},
        )

        plt.axis("equal")
        plt.axis("off")
        plt.tight_layout()
        plt.show()


class ComponentMetaClass(type(hk.Module)):
    """
    This metaclass enable the construction of model from components with a simple
    syntax while style enabling the components to be used as haiku modules.
    """

    def __call__(self, **kwargs):
        """
        This method enable to use model components as haiku modules when folded in a haiku transform
        function and also to instantiate them as SpectralModel when out of a haiku transform
        """

        if not base.frame_stack:
            return SpectralModel.from_component(self, **kwargs)

        else:
            return super().__call__(**kwargs)


class ModelComponent(hk.Module, ABC, metaclass=ComponentMetaClass):
    """
    Abstract class for model components
    """

    type: str

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
