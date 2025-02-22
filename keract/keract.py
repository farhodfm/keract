import json
import os
from collections import OrderedDict

import keras.backend as K
from keras.models import Model


def _evaluate(model: Model, nodes_to_evaluate, x, y=None):
    if not model._is_compiled:
        if model.name in ['vgg16', 'vgg19', 'inception_v3', 'inception_resnet_v2', 'mobilenet_v2', 'mobilenetv2']:
            print('Transfer learning detected. Model will be compiled with ("categorical_crossentropy", "adam").')
            print('If you want to change the default behaviour, then do in python:')
            print('model.name = ""')
            print('Then compile your model with whatever loss you want: https://keras.io/models/model/#compile.')
            print('If you want to get rid of this message, add this line before calling keract:')
            print('model.compile(loss="categorical_crossentropy", optimizer="adam")')
            model.compile(loss='categorical_crossentropy', optimizer='adam')
        else:
            print('Please compile your model first! https://keras.io/models/model/#compile.')
            print('If you only care about the activations (outputs of the layers), '
                  'then just compile your model like that:')
            print('model.compile(loss="mse", optimizer="adam")')
            raise Exception('Compilation of the model required.')

    def eval_fn(k_inputs):
        return K.function(k_inputs, nodes_to_evaluate)(model._standardize_user_data(x, y))

    try:
        return eval_fn(model._feed_inputs + model._feed_targets + model._feed_sample_weights)
    except:
        return eval_fn(model._feed_inputs)


def get_gradients_of_trainable_weights(model, x, y):
    """
    Get the gradients of trainable_weights for the kernel and the bias nodes for all filters in each layer.
    Trainable_weights gradients are averaged over the minibatch.
    :param model: keras compiled model or one of ['vgg16', 'vgg19', 'inception_v3', 'inception_resnet_v2',
    'mobilenet_v2', 'mobilenetv2']
    :param x: inputs for which gradients are sought (averaged over all inputs if batch_size > 1)
    :param y: outputs for which gradients are sought
    :return: dict mapping layers to corresponding gradients (filter_h, filter_w, in_channels, out_channels)
    """
    nodes = model.trainable_weights
    nodes_names = [w.name for w in nodes]
    return _get_gradients(model, x, y, nodes, nodes_names)


def get_gradients_of_activations(model, x, y, layer_name=None):
    """
    Get gradients of the outputs of the activation functions, regarding the loss.
    Intuitively, it shows how your activation maps change over a tiny modification of the loss.
    :param model: keras compiled model or one of ['vgg16', 'vgg19', 'inception_v3', 'inception_resnet_v2',
    'mobilenet_v2', 'mobilenetv2']
    :param x: inputs for which gradients are sought 
    :param y: outputs for which gradients are sought
    :param layer_name: if gradients of a particular layer are sought
    :return: dict mapping layers to corresponding gradients of activations (batch_size, output_h, output_w, num_filters)
    """
    nodes = [layer.output for layer in model.layers if layer.name == layer_name or layer_name is None]
    if layer_name is None:
        nodes.pop()  # last node output does not have any gradient, does it?
    nodes_names = [n.name for n in nodes]
    return _get_gradients(model, x, y, nodes, nodes_names)


def _get_gradients(model, x, y, nodes, nodes_names):
    if model.optimizer is None:
        raise Exception('Please compile the model first. The loss function is required to compute the gradients.')
    grads = model.optimizer.get_gradients(model.total_loss, nodes)
    gradients_values = _evaluate(model, grads, x, y)
    result = dict(zip(nodes_names, gradients_values))
    return result


def get_activations(model, x, layer_name=None):
    """
    Get output activations for all filters for each layer
    :param model: keras compiled model or one of ['vgg16', 'vgg19', 'inception_v3', 'inception_resnet_v2',
    'mobilenet_v2', 'mobilenetv2']
    :param x: input for which activations are sought (can be a batch input)
    :param layer_name: if activations of a particular layer are sought
    :return: dict mapping layers to corresponding activations (batch_size, output_h, output_w, num_filters)
    """
    nodes = [layer.output for layer in model.layers if layer.name == layer_name or layer_name is None]
    # we process the placeholders later (Inputs node in Keras). Because there's a bug in Tensorflow.
    input_layer_outputs, layer_outputs = [], []
    [input_layer_outputs.append(node) if 'input_' in node.name else layer_outputs.append(node) for node in nodes]
    activations = _evaluate(model, layer_outputs, x, y=None)
    activations_dict = OrderedDict(zip([output.name for output in layer_outputs], activations))
    activations_inputs_dict = OrderedDict(zip([output.name for output in input_layer_outputs], x))
    result = activations_inputs_dict.copy()
    result.update(activations_dict)
    return result


def display_activations(activations, cmap=None, save=False, directory='.', data_format='channels_last'):
    """
    Plot the activations for each layer using matplotlib
    :param activations: dict - mapping layers to corresponding activations (1, output_h, output_w, num_filters)
    :param cmap: string - a valid matplotlib colormap to be used
    :param save: bool - if the plot should be saved
    :param directory: string - where to store the activations (if save is True)
    :param data_format: string - one of "channels_last" (default) or "channels_first".
    The ordering of the dimensions in the inputs. "channels_last" corresponds to inputs with
    shape (batch, steps, channels) (default format for temporal data in Keras) while "channels_first"
    corresponds to inputs with shape (batch, channels, steps).
    :return: None
    """
    import matplotlib.pyplot as plt
    import math
    index = 0
    for layer_name, acts in activations.items():
        print(layer_name, acts.shape, end=' ')
        if acts.shape[0] != 1:
            print('-> Skipped. First dimension is not 1.')
            continue

        print('')
        # channel first
        if data_format == 'channels_last':
            c = -1
        elif data_format == 'channels_first':
            c = 1
        else:
            raise Exception('Unknown data_format.')

        nrows = int(math.sqrt(acts.shape[c]) - 0.001) + 1  # best square fit for the given number
        ncols = int(math.ceil(acts.shape[c] / nrows))
        hmap = None
        if len(acts.shape) <= 2:
            """
            print('-> Skipped. 2D Activations.')
            continue
            """
            # no channel
            fig, axes = plt.subplots(1, 1, squeeze=False, figsize=(24, 24))
            img = acts[0, :]
            hmap = axes.flat[0].imshow([img], cmap=cmap)
            axes.flat[0].axis('off')
        else:
            fig, axes = plt.subplots(nrows, ncols, squeeze=False, figsize=(24, 24))
            for i in range(nrows * ncols):
                if i < acts.shape[c]:
                    if len(acts.shape) == 3:
                        if data_format == 'channels_last':
                            img = acts[0, :, i]
                        elif data_format == 'channels_first':
                            img = acts[0, i, :]
                        else:
                            raise Exception('Unknown data_format.')
                        hmap = axes.flat[i].imshow([img], cmap=cmap)
                    elif len(acts.shape) == 4:
                        if data_format == 'channels_last':
                            img = acts[0, :, :, i]
                        elif data_format == 'channels_first':
                            img = acts[0, i, :, :]
                        else:
                            raise Exception('Unknown data_format.')
                        hmap = axes.flat[i].imshow(img, cmap=cmap)
                axes.flat[i].axis('off')
        fig.suptitle(layer_name)
        fig.subplots_adjust(right=0.8)
        cbar = fig.add_axes([0.85, 0.15, 0.03, 0.7])
        fig.colorbar(hmap, cax=cbar)
        if save:
            if not os.path.exists(directory):
                os.makedirs(directory)
            output_filename = os.path.join(directory, '{0}_{1}.png'.format(index, layer_name.split('/')[0]))
            plt.savefig(output_filename, bbox_inches='tight')
        else:
            plt.show()
        # pyplot figures require manual closing
        index += 1
        plt.close(fig)


def display_heatmaps(activations, input_image, directory='.', save=False, fix=True):
    """
    Plot heatmaps of activations for all filters overlayed on the input image for each layer
    :param activations: dict mapping layers to corresponding activations with the shape
    (1, output height, output width, number of filters)
    :param input_image: numpy array, input image for the overlay
    :param save: bool, if the plot should be saved
    :param fix: bool, if automated checks and fixes for incorrect images should be run
    :param directory: string - where to store the activations (if save is True)
    :return: None
    """
    from PIL import Image
    import matplotlib.pyplot as plt
    from sklearn.preprocessing import MinMaxScaler
    import numpy as np
    import math
    
    data_format = K.image_data_format()
    if fix:
        # fixes common errors made when passing the image
        # I recommend the use of keras' load_img function passed to np.array to ensure
        # images are loaded in in the correct format
        # removes the batch size from the shape
        if len(input_image.shape) == 4:
            input_image = input_image.reshape(input_image.shape[1], input_image.shape[2], input_image.shape[3])
        # removes channels from the shape of grayscale images
        if len(input_image.shape) == 3 and input_image.shape[2] == 1:
            input_image = input_image.reshape(input_image.shape[0], input_image.shape[1])

    index = 0
    for layer_name, acts in activations.items():
        print(layer_name, acts.shape, end=' ')
        if acts.shape[0] != 1:
            print('-> Skipped. First dimension is not 1.')
            continue
        if len(acts.shape) <= 2:
            print('-> Skipped. 2D Activations.')
            continue
        print('')
        nrows = int(math.sqrt(acts.shape[-1]) - 0.001) + 1  # best square fit for the given number
        ncols = int(math.ceil(acts.shape[-1] / nrows))
        fig, axes = plt.subplots(nrows, ncols, figsize=(12, 12))
        fig.suptitle(layer_name)

        # computes values required to scale the activations (which will form our heat map) to be in range 0-1
        scaler = MinMaxScaler()
        # reshapes to be 2D with an automaticly calculated first dimension and second
        # dimension of 1 in order to keep scikitlearn happy
        scaler.fit(acts.reshape(-1, 1))

        # loops over each filter/neuron
        for i in range(nrows * ncols):
            if i < acts.shape[-1]:
                if len(acts.shape) == 3:
                    #gets the activation of the ith layer
                    if data_format == 'channels_last':
                        img = acts[0, :, i]
                    elif data_format == 'channels_first':
                        img = acts[0, i, :]
                    else:
                        raise Exception('Unknown data_format.')
                elif len(acts.shape) == 4:
                    if data_format == 'channels_last':
                        img = acts[0, :, :, i]
                    elif data_format == 'channels_first':
                        img = acts[0, i, :, :]
                    else:
                        raise Exception('Unknown data_format.')
                        
                # scales the activation (which will form our heat map) to be in range 0-1 using
                # the previously calculated statistics
                if len(img.shape()) == 1:
                    img = scaler.transform(img.reshape(-1, 1))
                else:
                    img = scaler.transform(img)
                print(img.shape())
                img = Image.fromarray(img)
                # resizes the activation to be same dimensions of input_image
                img = img.resize((input_image.shape[0], input_image.shape[1]), Image.LANCZOS)
                img = np.array(img)
                axes.flat[i].imshow(input_image / 255.0)
                # overlay the activation at 70% transparency  onto the image with a heatmap colour scheme
                # Lowest activations are dark, highest are dark red, mid are yellow
                axes.flat[i].imshow(img, alpha=0.3, cmap='jet', interpolation='bilinear')
            axes.flat[i].axis('off')
        if save:
            if not os.path.exists(directory):
                os.makedirs(directory)
            output_filename = os.path.join(directory, '{0}_{1}.png'.format(index, layer_name.split('/')[0]))
            plt.savefig(output_filename, bbox_inches='tight')
        else:
            plt.show()
        index += 1
        plt.close(fig)


def display_gradients_of_trainable_weights(gradients, directory='.', save=False):
    """
    Plot in_channels by out_channels grid of grad heatmaps each of dimensions (filter_h, filter_w)
    :param gradients: dict mapping layers to corresponding gradients (filter_h, filter_w, in_channels, out_channels)
    :param save: bool- if the plot should be saved
    :param directory: string - where to store the activations (if save is True)
    :return: None
    """
    import matplotlib.pyplot as plt

    index = 0
    for layer_name, grads in gradients.items():
        if len(grads.shape) != 4:
            print(layer_name, ": Expected dimensions (filter_h, filter_w, in_channels, out_channels). Got ",
                  grads.shape)
            continue
        print(layer_name, grads.shape)
        nrows = grads.shape[-1]
        ncols = grads.shape[-2]
        fig, axes = plt.subplots(nrows, ncols, figsize=(12, 12))
        fig.suptitle(layer_name)
        hmap = None
        for i in range(nrows):
            for j in range(ncols):
                g = grads[:, :, j, i]
                hmap = axes[i, j].imshow(g, aspect='auto')  # May cause distortion in case of in_out channel difference
                axes[i, j].axis('off')
        fig.subplots_adjust(right=0.8, wspace=0.02, hspace=0.3)
        cbar = fig.add_axes([0.85, 0.15, 0.03, 0.7])
        fig.colorbar(hmap, cax=cbar)
        if save:
            if not os.path.exists(directory):
                os.makedirs(directory)
            output_filename = os.path.join(directory, '{0}_{1}.png'.format(index, layer_name.split('/')[0]))
            plt.savefig(output_filename, bbox_inches='tight')
        else:
            plt.show()
        index += 1
        plt.close(fig)


def persist_to_json_file(activations, filename):
    """
    Persist the activations to the disk
    :param activations: activations (dict mapping layers)
    :param filename: output filename (JSON format)
    :return: None
    """
    with open(filename, 'w') as w:
        json.dump(fp=w, obj=OrderedDict({k: v.tolist() for k, v in activations.items()}), indent=2, sort_keys=False)


def load_activations_from_json_file(filename):
    """
    Read the activations from the disk
    :param filename: filename to read the activations from (JSON format)
    :return: activations (dict mapping layers)
    """
    import numpy as np
    with open(filename, 'r') as r:
        d = json.load(r, object_pairs_hook=OrderedDict)
        activations = OrderedDict({k: np.array(v) for k, v in d.items()})
        return activations
