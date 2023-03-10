Lumos
=====

Let there be light!

Lumos is a collection of tools and utility constructs to enable smart computer vision applications.

Pre-requisites
--------------

* [Python 2.7.x](http://www.python.org/)
* [NumPy](http://www.numpy.org/) (lumos doesn't need SciPy, just NumPy, but it doesn't hurt)
* [OpenCV 4.2.0](http://opencv.org/)
* [PyZMQ](http://zeromq.org/bindings:python) (optional, for streaming/pub-sub servers)

Windows users, please note: NumPy binaries are not available for 64-bit Python, so get 32-bit, or build NumPy from source. Also setup [Python bindings for OpenCV](http://docs.opencv.org/trunk/doc/py_tutorials/py_setup/py_setup_in_windows/py_setup_in_windows.html).

Installation and usage
----------------------

1. Clone:
    
    ```bash
    $ git clone git@github.com:napratin/lumos.git
    ```

2. Install:
    
    ```bash
    $ [sudo] python setup.py develop
    ```
    
    Note: This installs lumos in [development mode](https://pythonhosted.org/setuptools/setuptools.html#develop-deploy-the-project-source-in-development-mode), which means lumos modules are exposed directly from the directory you cloned it in. You can then `git pull` to update your local copy, and/or make changes yourself. You can also use `[sudo] python setup.py install` for a typical installation (recommended: [Python virtual environment](http://docs.python-guide.org/en/latest/dev/virtualenvs/)).

3. Run:
    
    ```bash
    $ python -m lumos.tools.camview
    ```

4. Develop:
    
    ```python
    """A sample lumos application."""

    import cv2  # OpenCV functions

    from lumos.base import FrameProcessor  # base processor class
    from lumos.input import run  # driver function

    class MyAwesomeProcessor(FrameProcessor):
      """Custom processor that selects hues based on current time."""
      
      def process(self, imageIn, timeNow):
        # Convert input Red-Green-Blue image to Hue-Saturation-Value
        hsv = cv2.cvtColor(imageIn, cv2.COLOR_BGR2HSV)
        h, s, v = cv2.split(hsv)  # split into 3 channels
        h = h.reshape(h.shape + (1,))
        
        # Pick desired hue range based on current time
        hue = int(((timeNow % 10) / 10) * 180)
        min_hue = max(0, hue - 10) 
        max_hue = min(180, hue + 10)
        
        # Apply mask to select pixels in hue range and return
        mask = cv2.inRange(h, min_hue, max_hue)
        imageOut = cv2.bitwise_and(imageIn, imageIn, mask=mask)
        return True, imageOut


    if __name__ == "__main__":
      # Run a custom processor instance (NOTE pass in class name)
      run(MyAwesomeProcessor, description="A sample lumos application")
    ```
    
    Included as `sample.py` (run: `$ python -m sample`).
